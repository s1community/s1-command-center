<p align="center">
  <img src="https://sentinelone.com/wp-content/uploads/2021/09/S1_Logo_Horizontal_Purple.png" alt="SentinelOne" width="320"/>
</p>

<h1 align="center">S1 Command Center</h1>

<p align="center">
  <strong>A professional GUI tool for SentinelOne console management, backup, restore, and migration.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#backup--restore">Backup & Restore</a> •
  <a href="#architecture">Architecture</a> •
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

## License

This software is provided **AS IS**, free of charge, for use by SentinelOne employees and authorized partners.

---

<p align="center">
  <strong>Built with ❤️ by the SentinelOne Community</strong>
</p>
