<h1 align="center">🛡️ S1 Command Center</h1>

<p align="center">
  <strong>A professional GUI tool for SentinelOne console management, backup, restore, migration, and many more console-related actions.</strong>
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

Built with Python and CustomTkinter, it delivers a modern UI with **light & dark themes**, real-time progress tracking, detailed reporting, and full audit trails.

## Features

### Console Management
- **Dual Console Connections** — Connect to SOURCE and DESTINATION consoles simultaneously
- **Paste from Ticket** — One-click import of migration ticket fields into all pages
- **Auto-connect** — Automatically reconnects to saved consoles on startup
- **Reset All** — Clear all fields and start a fresh migration in one click
- **Settings Page** — A ⚙ Settings panel (sidebar footer) for theme (Light / Dark / System), UI scale, start-in-fullscreen, OUTPUT-console-on-launch, default snapshot-first, OS-keychain storage, and default ignore-SSL; preferences persist across restarts **and app updates**

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
- **Account-name guard** — Warns before restoring if the backup's account name isn't on the destination console and offers to jump to Structure Operations → Mangle Rename, so you don't accidentally create a brand-new account
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
- **Tags** — Audit what tags a console actually holds, scope by scope, own vs inherited — plus a write probe that diagnoses why endpoint tag creation silently fails
- **Raw API** — Direct API access for any endpoint

## Installation

### macOS — one-line install (recommended)

Open Terminal and paste:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
```

That's it. The installer downloads the latest DMG, copies the app to `/Applications`, strips the macOS quarantine flag, and launches it. **No Gatekeeper prompts, no System Settings hunting** — because the script runs entirely inside Terminal (Gatekeeper only enforces on Finder double-clicks), and the quarantine flag is cleared before the app's first launch.

<details>
<summary>Optional flags</summary>

```bash
# pin a specific version
S1CC_VERSION=v2.2.0 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"

# install but don't auto-launch
S1CC_NO_LAUNCH=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
```
</details>

### macOS — manual DMG install

1. Download the latest `S1-Command-Center-macOS.dmg` from [Releases](https://github.com/s1community/s1-command-center/releases/latest).
2. Open the DMG, drag `S1 Command Center.app` onto the `Applications` shortcut.
3. First launch: see [Troubleshooting → macOS](#macos--app-is-not-from-an-identified-developer) below.

### Windows

Download either:
- `S1-Command-Center-Windows-Setup.exe` — full installer (Start Menu + uninstaller).
- `S1-Command-Center-Windows.zip` — portable, unzip and run.

### Run from source (any platform)

#### Prerequisites
- **Python 3.10+** (tested on 3.11, 3.12, 3.13)
- **macOS**, **Windows**, or **Linux**

#### Setup

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
| Tags (Endpoint) | ✅ | ✅ | Two different objects: device inventory (Ranger) tags via `/tags`, and unified endpoint tags via the Tag Manager API — the latter needs its own token permission |
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

Only applies if you installed manually from the DMG. If you used the [one-line installer](#macos--one-line-install-recommended), Gatekeeper is bypassed entirely and you'll never see this prompt.

**Fastest fix** — one Terminal command:

```bash
xattr -cr "/Applications/S1 Command Center.app"
```

Then double-click the app normally. That strips the `com.apple.quarantine` flag macOS attaches to anything downloaded from the internet, which is what Gatekeeper checks against.

**GUI fix** — authorize through Settings:

1. Click the **Apple Menu ()** in the top-left corner and select **System Settings** (or System Preferences).
2. Navigate to **Privacy & Security**.
3. Scroll to the bottom — you'll see *"S1 Command Center" was blocked from use because it is not from an identified developer*.
4. Click **Open Anyway**.
5. Enter your Mac password or use Touch ID when prompted.
6. Click **Open** on the final confirmation pop-up.

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
├── migtools.py       # Pure migration logic (preflight, reconciliation, diffs)
├── tag_audit.py      # Tag audit & endpoint-tag write probe (Tags page core)
├── theme.py          # Colour palette, fonts, widget theming
├── tests/            # pytest suite (no console required — fakes throughout)
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

API tokens are written to that file with owner-only (`0600`) permissions. OS-keychain storage is **off by default** — on macOS it otherwise prompts for the login-keychain password on every token read/write. To store tokens in the OS keychain instead (macOS Keychain / Windows Credential Manager / Secret Service), set `S1CC_ENABLE_KEYRING=1`.

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
| `Tags.view`, `Tags.create` | Backup/restore firewall / network-quarantine / device-inventory tags |
| `Tag Management.view`, `Tag Management.create` | Backup/restore unified endpoint tags (Tag Manager) |
| `ThreatIntelligence.view`, `ThreatIntelligence.create` | Backup/restore IOCs |

> **Endpoint tags need their own permission.** `Tags.create` does *not* cover the Tag Manager route. A token with only `Tags.create` restores firewall tags and leaves the destination's endpoint tag list empty. If tags go missing after a restore, the **Tags** page audits what the console really holds and diagnoses which half is failing.

> **Recommendation:** Use a Service User with **Admin** role for full access.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -am 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## Usage Dashboard

Live download analytics for every release, broken down by version and platform:

**[s1community.github.io/s1-command-center](https://s1community.github.io/s1-command-center/)**

Pure static page reading the public GitHub Releases API — no telemetry shipped from the app, no PII collected.

## Changelog

### v2.2.4 — 2026-08-21
#### Bug Fixes
- **The tag diagnosis stated a cause it hadn't proven** — "no format worked" was reported as a missing `Tag Management.create` permission. A global-admin token with that permission granted produced the same verdict, because asking a single listing route and discarding the console's reply can't tell "discarded the write" from "stored it somewhere else". Both are now reported, each with its own next step.
- **Endpoint tags were only looked for on `GET /agents/tags`** — a console serving them elsewhere was reported as having none. Every known route is tried, and the answering route is named.
- **Read-back matched the `key` field exactly** — `tagName` and `name` now count, case-insensitively.

#### New
- **The console's raw response is recorded per request format** and logged, so a create the console claims but nothing can list is its own verdict rather than a silent no-op.
- **The diagnosis can be saved as a report** — formats, outcomes, routes and raw responses, for sending on.

### v2.2.3 — 2026-08-19
#### Bug Fixes
- **Result tables drew their first row over the column headers** — a batched load numbered the first row one place too high, so it shared a grid row with the header. Affected every operations page; most visible on the Tags audit, where "own" appeared printed over "owned".

### v2.2.2 — 2026-08-16
#### New
- **Tag audit, built into the app** — the v2.2.1 audit was a command-line script, which meant cloning the repo to answer "did my tags actually land?". It's now the **Tags** page (Operations → Inventory). **Run Audit** is read-only and lists every tag the chosen console really holds, per scope, from both tag APIs, separating each scope's own tags from inherited ones — filterable by tag type, account and site, and exportable. **Diagnose endpoint tags** writes (with confirmation): it tries each request format `POST /tag-manager` may accept using throwaway `s1cc-probe-…` keys, re-reads to see which one actually stored, deletes them again, and reports either the format that works or that the console accepts and discards everything — what a token without `Tag Management.create` looks like.
- **An empty endpoint tag list explains itself** — if the audit finds none, the summary says so and points at the diagnosis rather than leaving a blank table.

#### Changed
- Restore errors for failed tag creates now point at the Tags page instead of a script.

### v2.2.1 — 2026-08-16
#### Bug Fixes
- **A tag create the console throws away is no longer reported as success** — `POST /tag-manager` answers `200` to a body it doesn't store, so a restore could report ~150 endpoint tags created against a destination whose Tag Manager list stayed empty. Creation now has to see a created object in the response (an id, a non-empty list, or a positive `affected` count) before it counts as new; anything else is an error on the node, not a phantom "N new". The request is also retried in each envelope the route accepts — but only after reading the tag back and confirming it isn't there, so a console that stores the tag and answers with an empty body can't end up with duplicates.
- **Failed endpoint tags are named properly** — key/value tags have no `name`, so the failure list showed only the value ("Finance"). It now reads `key=value`.

#### New
- **Tag audit tooling** — lists every tag a console actually holds, per scope, separating a scope's own tags from inherited ones, so you can confirm a restore landed without re-running it. An opt-in write probe finds which `POST /tag-manager` body the console really stores and cleans up after itself. Shipped here as a script; moved into the Tags page in v2.2.2.

#### Docs
- **Endpoint tags need `Tag Management.create`** — a separate permission from `Tags.create`, now listed in the API token permissions page.

### v2.2.0 — 2026-08-13
#### Bug Fixes
- **Endpoint tags are finally restored** — selecting **tags_endpoint** backed the tags up, counted them in preview/validation and listed them in the restore report, but the restore loop had no branch for them at all: nothing was created on the destination and no error was raised, so a "restore tags" run looked successful while the destination stayed empty. Device-inventory tags now restore through `/tags` and unified endpoint tags through the Tag Manager API.
- **Endpoint tag backup hit a route that doesn't exist** — unified endpoint tags were read from `/endpoint-tags`, which isn't a SentinelOne API endpoint. The 404 was swallowed as "n/a", so those tags were never in the backup file in the first place. Listing now uses `/agents/tags` and creation `POST /tag-manager`.
- **Firewall / network-quarantine tag creation no longer sends read-only fields** — the create payload carried `kind`, which the console rejects, and omitted the tag scope. Payloads are now rebuilt from the writable fields only, with the destination scope stamped in (and a retry without it for consoles that don't accept it).
- **Inherited tags no longer duplicate down the tree** — `GET /tags` returns the tags a scope inherits from its parents, so restoring a site re-created the account and global tags at site level. Tags are now filtered to the scope that actually owns them, matching the existing firewall / device-control / STAR behaviour.
- **A tag step that does nothing now says so** — every selected tag group reports a row (`0` included) instead of silently disappearing from the restore report.

#### Tests
- New restore-coverage guard: every element the backup captures must have a restore branch (or a documented exception), so "backed up but never restored" can't ship again. Plus coverage for tag scope filtering, tag/endpoint-tag payload building, and the corrected API routes. 180 tests total.

### v2.1.10 — 2026-07-29
#### Bug Fixes
- **Saved filters now actually restore — and dynamic groups stay dynamic** — a migrated site could come out with none of its Deep Visibility filters, every dynamic group downgraded to **static**, and an empty **Group Ranking** page. All three were the same bug: `/filters` reports a filter's own scope as `scopeLevel`, and that source value was still being sent in the create payload even though the destination scope travels separately in the request's `filter` envelope. The console rejected every create, so no filters landed; group restore then couldn't resolve each dynamic group's filter by name and created it static, and S1 only ranks dynamic groups, so ranking came up empty. `scopeLevel` is now stripped alongside the other scope references. Re-running a restore repairs an affected site.

#### New
- **Export STAR rules to Excel** — a **⭐ STAR → Excel** button on the Backup page reads every custom detection rule live from the selected console (no backup required) and writes a two-sheet workbook: a *Summary* with totals and breakdowns by scope / status / severity / account, and a *STAR Rules* sheet with all 24 fields per rule, frozen header, auto-filter on, and colour-coded scope / status / severity. Honours the page's Account Name / Site Name filters.
- **Targeted STAR rule cleanup** — the cleanup script gained `--site-name` / `--site-id` and `--mode all-site-scoped`, to strip every site-scoped rule from a site that a pre-2.1.9 build filled with copies of the tenant's global ruleset.

### v2.1.9 — 2026-07-28
#### Bug Fixes
- **Custom detection (STAR) rules no longer duplicate across scopes** — an account-scoped rule was captured at the account *and* under every child site, then re-created at each one, so a single rule ended up repeated per site on the destination. The `/cloud-detection/rules` API returns inherited rules at every scope level; backup and restore now filter each rule to its own scope, matching the existing firewall / device-control behaviour. The restore-side filter also repairs backups taken with earlier builds, so no re-capture is needed.

#### New
- **Duplicate STAR rule cleanup script** — `scripts/cleanup_duplicate_star_rules.py` finds site-scoped rules that duplicate an account/global rule and bulk-deletes them through the Delete Rules API (the console UI can't filter or bulk-select by site scope). Dry-run by default; `--delete` to apply.

### v2.1.8 — 2026-07-28
#### Bug Fixes
- **Backup name filters now prefer an exact match** — typing a specific **Site Name** like `Servers` no longer also backs up supersets such as `HighQ_Servers` or `TR-Servers`. When a name matches exactly it wins; if nothing matches exactly, partial (substring) matching still works as a fallback. The same exact-preferred rule applies to the **Account Name** and **Group Name** filters and the migration/preview tree.

### v2.1.7 — 2026-07-27
#### Bug Fixes
- **Custom RBAC roles now restore correctly** — role creation was rejected with "Unknown field" / "Missing required field" validation errors. Restore now sends the role scope as the required top-level `filter`, drops the read-only fields the API rejects (`scope`, `predefinedRole`, `accountIds`, `pages`), and rebuilds each role from the destination console's own role template so permissions carry over even across consoles with different licensed features.
- **Backup account matching is more reliable** — Account Name filters now normalize invisible Unicode/control characters, copied rich-text spacing, and case before matching API account names. If a stale ticket account ID is present, backup falls back to the visible Account Name instead of returning 0 nodes.

### v2.1.6 — 2026-07-22
#### Bug Fixes
- **API calls no longer fail with opaque decompression errors** — requests now prefer uncompressed JSON responses, and any bad compressed response is wrapped with the API endpoint and a clear decode-failure message.

### v2.1.5 — 2026-07-22
#### Improvements
- **Account-scoped RBAC roles are now backed up and restored** — role backup now queries the selected account scope and captures full role definitions; restore re-creates custom account roles before creating console users so role assignments can map by name.
- **Restore element info icons work again** — the ⓘ buttons now open hover/click tooltips instead of silently writing help text to the output console.
- **Restore log export defaults to JSON** — JSON is now the default export format, and the HTML report expands the full operation log by default when selected.
- **Source vs destination validation now compares every item** — large exclusion sets are no longer sampled at 50 entries, so missing path exclusions deep in a 300-item list are surfaced in the validation export.
- **Operations → Exclusions & Blocklist is scope-aware** — add Account/Site filters to load account/site-scoped exclusions instead of only tenant-scoped entries.

### v2.1.4 — 2026-07-14
#### Improvements
- **Restore progress bar redesigned** — the bar, timer, and live status no longer float to the right of the RUN buttons with a big gap; they now sit in a dedicated full-width strip directly under the buttons (bar spans the page, timer + status right-aligned).

### v2.1.3 — 2026-07-14
#### Improvements
- **macOS Keychain toggle now warns before it bites** — Enabling "Store API tokens in OS keychain" on an unsigned build makes macOS prompt for keychain permission on every launch and after every update. The toggle now confirms this before enabling and reverts if you decline. Default stays OFF (owner-only `0600` file, no prompts). Getting the prompt after an upgrade? Turn this toggle OFF in Settings → Security & Storage.

### v2.1.2 — 2026-07-14
#### Bug Fixes
- **Restore no longer looks like it's stuck "Snapshotting" while it's actually restoring** — the pre-restore snapshot label (`📸 Snapshot …`) lingered on the status line for the whole restore. It's now cleared when the snapshot finishes, and the restore shows a live `Restoring i/total: <node>…` label so the current phase is always clear.

### v2.1.1 — 2026-07-14
Restore reliability release.
#### Bug Fixes
- **Policy restore no longer fails on forensics auto-triggering** — Restoring a policy whose `forensicsAutoTriggering` references a RemoteOps forensic-script profile that doesn't exist on the destination failed the whole policy with *"Bad auto-triggering policy information provided (code 4000010)"*. Restore now drops just that block and retries so the rest of the policy lands. Verified live.
- **STAR custom-detection rules no longer rejected on restore** — Creating a STAR rule failed with *"data: activeResponse: Unknown field (code 4000010)"*; the read-only `activeResponse` field is now stripped before create. Verified live.
#### Improvements
- **"Snapshot first" is now interruptible and shows progress** — the pre-restore destination snapshot shows per-node progress (`i/total: path`) and honors **Skip**/**Stop** mid-snapshot instead of looking frozen (captured data is still saved for rollback).
- **Per-element Skip button** — the Skip button names the element/phase currently running (e.g. "⏭ Skip FW rules") and every restore step honors it and re-enables between elements, so each element is independently skippable.

### v2.1.0 — 2026-07-13
UI/UX release.
#### New
- **Settings page** — a **⚙ Settings** button in the sidebar footer opens a preferences page: **theme (Light / Dark / System)**, UI scale, start-in-fullscreen, open OUTPUT console on launch, default "Snapshot first" for restores, OS-keychain token storage, and default "Ignore SSL errors" for new connections. Preferences auto-save (plus a **Save Settings** button) to `~/.s1-command-center/settings.json` and **persist across restarts and app updates**.
- **Light / Dark mode** — a full light theme with a live Light / Dark / System switch.
#### Improvements
- **Restore page re-organized by workflow** — the action bar is grouped into three labeled phases: **1 · Prepare** (Pre-flight, Preview vs Dest, Set Defaults, Snapshot first), **2 · Run** (Restore, Auto Restore, Resume, Stop, Skip Element), and **3 · Review** (Export Log, Explain Errors, Redacted Copy, Rollback).
- **Restore account-name guard** — if none of the backup's account names exist on the destination console, the app warns before restoring and offers to jump to Structure Operations → Mangle Rename, so you don't accidentally create a brand-new account.
- **Picture logo** — the sidebar shows the app's radar logo instead of the text "S1" tile (falls back to the tile if unavailable).
- **Fullscreen** — toggle with ⌘⇧F (or F11); press Esc to exit.
- **Help tooltips** — the "?" buttons now show a hover/click tooltip instead of writing help into the OUTPUT console.
#### Bug Fixes
- **App no longer closes itself on macOS** — a help tooltip used a `-topmost` borderless window that could tear down the whole app a few seconds after launch. Fixed (plus a regression check).

### v2.0.3 — 2026-07-13
#### Bug Fixes
- **App no longer crashes on startup** — v2.0.1 and v2.0.2 crashed immediately on launch with `NameError: name 'APP_VERSION' is not defined`: the sidebar footer referenced the app version without `app.py` importing it. Fixed the import and added a regression test so it can't recur.

### v2.0.2 — 2026-07-13
#### Improvements
- **No more macOS keychain prompts** — OS-keychain token storage is now opt-in (`S1CC_ENABLE_KEYRING=1`) instead of on by default, so macOS no longer shows the "S1 Command Center wants to use your confidential information…" login-keychain prompt on every token read/write. Tokens are kept in the owner-only (`0600`) `contexts.json` unless you opt back in.

### v2.0.1 — 2026-07-13
#### Improvements
- **Reset All is a true clean slate** — 🔄 Reset All now permanently deletes every saved connection (source & destination, plus their OS-keyring tokens) in addition to clearing all page fields, so nothing carries over into the next migration.
- **Jira-ready completion report** — The Migration Complete popup's "📋 Copy All" text now leads with a `cc: @migration-team` mention placeholder and a `Migration was completed with S1 Command Center vX.Y.Z for the <scope>` summary line, ready to paste into the ticket.

### v2.0.0 — 2026-07-08
Major version milestone — rolls up the v1.7–v1.8 migration-workflow & verification work into a stable **2.0**, plus the firewall-rule migration fixes below.
#### Bug Fixes
- **Multi-IP firewall rules transfer completely** — Rules with more than one remote host (IP, CIDR, or FQDN) were restored with only the first entry. SentinelOne stores multiple hosts in the plural `remoteHosts`/`localHosts` arrays, but the restore whitelist kept only the legacy singular `remoteHost`/`localHost`. Fixed — all hosts now migrate. (Multiple *ports* were never affected.)
- **Inherited firewall rules no longer leak into child-scope restores** — A site/group restore no longer re-creates the account/global rules that the API returns as inherited; firewall rules are filtered to the node's own scope (matching Device Control). Fixes account-scoped rules still being restored after unchecking the **Account** restore level.

### v1.8.0 — 2026-06-30
#### Migration workflow
- **Migration Runbook** — Guided, ordered checklist for the whole job: connect → pre-flight → backup → preview → restore → validate → manifest.
- **Pre-flight readiness check** — Validates destination reachability, token validity/scope, and target existence *before* you commit (read-only pass/warn/fail).
- **Agent-migration reconciliation** — ✓ Verify Move reconciles source/destination counts and lists stragglers after an agent move.
#### Verification
- **Field-level settings/policy diff** — Policy, the three module configs, and SSO/SMTP/syslog/AD now get a value-level field diff, not just present/absent.
#### Operations
- **Operation audit history** — Every backup/restore/validate/agent-migrate is appended to `~/.s1-command-center/audit.jsonl`; a 📜 History button shows recent operations.
- **Scheduled backups** — ⏰ interval selector (Hourly/6h/12h/Daily) runs the current backup automatically while the app is open.

### v1.7.0 — 2026-06-29
#### Reliability / scale
- **Rate-limit visibility** — The API client tracks HTTP 429 throttling and says so in the log when a job slows down, instead of appearing frozen.
#### Security
- **API tokens can live in the OS keyring** — When `keyring` and a working OS backend (macOS Keychain / Windows Credential Manager / Secret Service) are present, tokens are stored there and `contexts.json` holds only a sentinel. Degrades gracefully to file storage.
- **Redacted backup export** — 🛡 Redacted Copy produces a sanitised backup JSON (SMTP/AD/SSO/syslog passwords, tokens, and keys masked) that's safe to attach to a ticket.
#### Build
- **Keyring bundled** — Build scripts and the PyInstaller spec now collect `keyring` + the platform backend so OS-keyring storage works in packaged apps.

### v1.6.0 — 2026-06-29
#### UI Redesign
- **New design system** — A complete visual overhaul built around the SentinelOne brand violet (`#7C3AED`) on a refined slate-charcoal dark theme, centralised in a new `theme.py` so the whole app themes from one place. Buttons, inputs, checkboxes, sliders, progress bars, scrollbars, and dropdowns all adopt the palette automatically.
- **Cross-platform fonts** — The UI now renders in the native system font per OS (SF Pro Text / Menlo on macOS, Segoe UI / Consolas on Windows, DejaVu on Linux) instead of Windows-only fonts that fell back to an unstyled default on macOS/Linux.
- **Redesigned sidebar** — Brand lockup with a violet logo mark, a connection-status card with live SRC/DST dots, section eyebrows, and a violet active-indicator bar on the selected page. The MIGRATION workflow sits in its own distinct violet-tinted panel, set apart from OPERATIONS.
- **OUTPUT console as a drawer** — The log is now a collapsible drawer that slides up from an always-visible status line (which mirrors the latest log entry, colour-coded). It's resizable via a drag handle and has an explicit Collapse control. Clicking any **?** help button opens it automatically.
- **Adaptive scaling** — The window opens proportional to your screen, and the whole UI auto-scales as the window grows so it never looks cramped on large/full-screen displays. Manual zoom via ⌘/Ctrl +/-/0.

#### Safety
- **Critical-operation lock** — While a backup or restore is running, every control except Stop / Skip Element (and the log drawer) is disabled, so nothing can disturb the running job or navigate away mid-operation.

#### Security & Quality
- **Credential files hardened** — Saved API tokens (`contexts.json`), Atlas cookies, and backup JSON files are now written with owner-only (`0600`) permissions, and the config directory is `0700`.
- **Reproducible builds** — Added `requirements-lock.txt` (fully pinned) and corrected an unsatisfiable `requests` version floor.
- **Test suite** — Added a pytest suite (API client retry/error handling + pure restore helpers) and `requirements-dev.txt`.
- **Backup error visibility** — Replaced silent `except: pass` blocks in the backup path with logged warnings, so a "0 nodes" or partial backup now explains itself in the OUTPUT log instead of failing silently.
- **Restore refactor** — Hoisted pure restore helpers to module level (now unit-tested) and de-duplicated the per-element summary logging.

### v1.5.0 — 2026-06-22
#### New Features
- **⚡ Auto Restore** — New button that runs a fully automatic migration with zero prompts. Automatically creates all missing accounts, sites, and groups on the destination. No confirmation dialogs, no filters — click and walk away.
- **↻ Resume** — New button to resume a previously stopped or failed restore from exactly where it left off. Already-completed nodes are skipped; cancelled and errored nodes are retried automatically.
- **Auto-create accounts** — When an account doesn't exist on the destination, a custom dialog offers three choices: **Create** (this account), **Create All** (all remaining), or **Skip**. Replaces the old system Yes/No/Cancel dialog with clear labels.
- **Auto-create sites & groups** — Sites and groups under auto-created accounts are created automatically during migration.
- **Filter bypass for global restores** — When the Global checkbox is checked (or Auto Restore / Create All is used), account/site/group name filters are automatically bypassed.

#### UI
- **Reorganized button layout** — Two clear rows with color-coded groups: Launch (green — Restore, Auto Restore, Resume), Control (red/orange — Stop, Skip Element), Results (blue — Export Log, Explain Errors), Setup (gray — Set Defaults).

#### Improvements
- **Smarter license handling** — Account creation strips add-on bundles (Purple AI, Ranger, etc.) and retries with fallbacks.
- **Auto-mode for site conflicts** — In Auto Restore mode, default-site conflicts and missing sites are resolved without prompts.
- **SKU fix auto-accept** — In Auto Restore mode, SKU/bundle mismatch fixes are applied automatically.

### v1.4.0 — 2026-06-03
#### New Features
- **Migration Validation page** — New MIGRATION tab that compares the **live source** console against the **live destination** and explains every difference in plain English. Matches accounts/sites/groups by name (rename-aware), then diffs every config element (policy, exclusions, blocklist, firewall rules/locations, device control, network quarantine, saved filters, config overrides) by count **and** by item name. The GUI shows a compact per-node summary with the exact missing/extra item names; the **Export Report** (HTML) lists every differing item by name with a "why" and "what to do" for each. Source/Destination URLs and scope entries are shown inline and auto-filled by **Paste from Clipboard** (ticket).

#### Dependencies
- Bumped `requests` (>= 2.34.2) and `Pillow` (>= 12.2.0). `customtkinter` (>= 5.2.2) and `openpyxl` (>= 3.1.5) unchanged (already latest).

### v1.3.8 — 2026-05-29
#### Analytics
- **Usage dashboard** — New static dashboard at [`docs/index.html`](docs/index.html) (live at [s1community.github.io/s1-command-center](https://s1community.github.io/s1-command-center/) once GitHub Pages is enabled). Reads the public GitHub Releases API and renders total downloads, macOS-vs-Windows split, per-version stacked-bar chart, platform doughnut, and a per-asset breakdown table. Auto-refreshes every 5 minutes. Zero client-side telemetry — no event collection from the app itself, just public release-download counts that GitHub already publishes.

### v1.3.7 — 2026-05-29
#### Documentation (macOS)
- **DMG `README.txt` and GitHub release notes now lead with the one-liner installer**, instead of "double-click the DMG to install" which sent users straight into the Gatekeeper trap. The drag-to-Applications flow stays as the fallback below.

### v1.3.6 — 2026-05-29
#### Packaging (macOS)
- **One-line installer** — New recommended install path: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"`. Downloads the latest DMG, copies to `/Applications`, strips `com.apple.quarantine`, launches. **Zero Gatekeeper prompts** because Terminal-invoked scripts bypass Gatekeeper, and the quarantine flag is cleared before any `open` call. Supports `S1CC_VERSION=vX.Y.Z` (pin) and `S1CC_NO_LAUNCH=1` (don't auto-launch).

### v1.3.5 — 2026-05-29
#### Packaging (macOS)
- **Dropped the `Install & Launch.command`** — macOS Sequoia (15.x) removed the right-click → Open Gatekeeper bypass for unsigned shell scripts, so the launcher script was itself getting blocked. DMG now uses the standard drag-to-Applications layout (app + `Applications` symlink) and the README explains the one-time *System Settings → Privacy & Security → Open Anyway* unblock flow.

### v1.3.4 — 2026-05-29
#### UI
- **New app icon** — Replaced the legacy icon with a command-center radar scope in SentinelOne brand purple (`#7C3AED`). Generated by `scripts/build_icon.py` at native resolutions for both platforms: Windows `.ico` (16…256) and macOS `.icns` (16…1024 incl. @2x). macOS builds now consume the native `.icns` directly.

### v1.3.3 — 2026-05-28
#### Packaging
- **Windows full installer** — Releases now ship `S1-Command-Center-Windows-Setup.exe` (built with Inno Setup 6) alongside the portable ZIP. Installs to `Program Files\S1 Command Center`, creates Start Menu + optional desktop shortcuts, and registers a proper uninstaller in *Add or Remove Programs*.

### v1.3.2 — 2026-05-28
#### Bug Fixes
- **Windows EDR false-positive on export** — Auto-opening exported reports via `os.startfile()` (Windows) / `subprocess.Popen(["open"|"xdg-open", ...])` (macOS/Linux) was tripping behavioral-detection thresholds in some endpoint agents (including S1 itself), causing the app to be quarantined immediately after the first export. Export now writes the file and logs its full path to the OUTPUT console instead of spawning a child process. Open exported files manually from the logged path.

#### Dependencies
- Bumped `customtkinter` (>= 5.2.2), `requests` (>= 2.32.3), `openpyxl` (>= 3.1.5), `Pillow` (>= 11.0.0).

### v1.3.1 — 2026-05-23
#### Bug Fixes
- **Exclusion paths with invisible Unicode characters** — Restore now scrubs U+200E (LTR mark), zero-width joiners, BOMs, etc. from exclusion `value`/`description` fields. Fixes destinations rejecting paths with `Invalid value <x> contains non-printable characters`.
- **Notification recipients payload shape** — `PUT /settings/recipients` now sends the list directly (was wrapped as `{"emails": [...]}`). Includes two fallback shapes to handle tenant variants. Fixes `data: dict_values(['emails']): Unknown field`.
- **Firewall rules with cross-console location bindings** — On `Invalid locations for this scope`, the migrator auto-retries with location fields stripped so the rule lands as location-agnostic. Operator gets a log warning to re-attach Locations manually.

#### Better Error Explanations
- "Cannot change firewall settings while inheriting from parent" → "Scope inherits from parent" with explicit decouple instructions.
- "Invalid locations for this scope" → dedicated explanation.
- "data: dict_values(['emails']): Unknown field" → dedicated explanation.

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
