# Supported Elements

S1 Command Center backs up and restores **33** configuration element types.
Most are fully re-created on the destination; a few are **inventory-only**
(backed up and listed for manual action, because the API can't re-create them
faithfully — see notes).

## Element Table

| # | Element | Backup | Restore | Scope | Notes |
|---|---------|:------:|:-------:|-------|-------|
| 1 | **Policy** | ✅ | ✅ | All | Full policy configuration |
| 2 | **Exclusions** | ✅ | ✅ | All | Legacy 5 types: hash, path, file type, certificate, browser |
| 3 | **Unified Exclusions** | ✅ | ✅ | All | v2.1 unified + tag-based exclusions |
| 4 | **Blocklist** | ✅ | ✅ | All | SHA1/SHA256 hash restrictions |
| 5 | **Firewall Rules** | ✅ | ✅ | All | Rule ordering preserved; location bindings auto-stripped on conflict |
| 6 | **Firewall Config** | ✅ | ✅ | All | Enabled, inheritance, location-aware |
| 7 | **NQ Config** | ✅ | ✅ | All | Network Quarantine configuration |
| 8 | **NQ Rules** | ✅ | ✅ | All | Network Quarantine allow-rules |
| 9 | **Device Control Rules** | ✅ | ✅ | All | USB, Bluetooth block/allow |
| 10 | **Device Control Config** | ✅ | ✅ | All | Enabled, reporting settings |
| 11 | **Tags (Firewall)** | ✅ | ✅ | All | Firewall rule classification tags |
| 12 | **Tags (NQ)** | ✅ | ✅ | All | Network quarantine tags |
| 13 | **Tags (Endpoint)** | ✅ | ✅ | All | Device inventory and unified tags |
| 14 | **STAR Rules** | ✅ | ✅ | Account, Site | S1QL custom detection rules; past expirations auto-extended |
| 15 | **Saved Filters** | ✅ | ✅ | Account, Site | Deep Visibility saved queries |
| 16 | **Threat Intel** | ✅ | ✅ | Account | IOC indicators (batched, up to 5000) |
| 17 | **Config Overrides** | ✅ | ✅ | All | Persistent agent config overrides |
| 18 | **Log Collection Rules** | ✅ | ✅ | Account, Site | XDR log ingestion rules |
| 19 | **Auto-upgrade Policies** | ✅ | ✅ | Account, Site | Agent upgrade schedules |
| 20 | **Locations** | ✅ | ✅ | Account, Site | Firewall location-awareness; auto-created Fallback skipped |
| 21 | **Notification Settings** | ✅ | ✅ | Account, Site, Global | Alert notification config + recipients |
| 22 | **SSO Settings** | ✅ | ✅ | Account, Site, Global | SAML single sign-on (SP-bound values retried) |
| 23 | **SMTP Settings** | ✅ | ✅ | Account, Site, Global | Email relay settings |
| 24 | **Syslog Settings** | ✅ | ✅ | Account, Site, Global | Syslog forwarding |
| 25 | **AD Settings** | ✅ | ✅ | Account, Site, Global | Active Directory integration |
| 26 | **Webhooks** | ✅ | ✅ | Account, Site, Global | Notification webhook endpoints |
| 27 | **Scheduled Reports** | ✅ | ✅ | Account, Site, Global | Saved/scheduled console reports |
| 28 | **Roles** | ✅ | ✅ | Account | RBAC custom role definitions |
| 29 | **Service Users** | ✅ | ✅ | Account | API service accounts |
| 30 | **Console Users** | ✅ | ✅ | Account | Locally-created users only (SSO/SCIM auto-provision); invitation email sent |
| 31 | **Gateways** | ✅ | ✅ | Account, Site | Management proxy configurations |
| 32 | **Marketplace Apps** | ✅ | 📋 | Account, Global | **Inventory only** — re-install manually (each needs its own OAuth/credentials) |
| 33 | **Remote Scripts** | ✅ | 📋 | Account, Global | **Inventory only** — script body lives in cloud storage, not in the API payload; listed for manual re-upload |

## Restore Legend

| Symbol | Meaning |
|:------:|---------|
| ✅ | Re-created on the destination via the API |
| 📋 | **Inventory only** — backed up and listed in the restore log for manual re-creation (the API cannot faithfully re-create it) |

## Scope Legend

| Scope | Meaning |
|-------|---------|
| **All** | Global, Account, Site, and Group levels |
| **Account, Site** | Account and Site levels only |
| **Account** | Account level only |
| **Account, Global** | Account and Global levels |
| **Account, Site, Global** | Settings that exist at account, site, or global level |

## Not Migratable (and why)

These were evaluated and intentionally **not** included as backup elements:

| Item | Reason |
|------|--------|
| **Custom Dashboards** | No public v2.1 REST/GraphQL CRUD endpoint exists for dashboards, so they cannot be read or re-created programmatically. Rebuild manually on the destination. |
| **Ranger / Network Discovery data** | The available endpoints (`/ranger/table-view`, `/rogues/table-view`) return *discovered-device runtime inventory*, not configuration. There is no scope-level "Ranger settings" config object exposed by the API to migrate. The Ranger *policy* toggle travels with **Policy** (#1). |

> If SentinelOne exposes a settable Ranger configuration or a dashboards API in
> a future release, these can be added as standard backup elements using the
> existing `_read_node` / `_run_restore` dispatch pattern.

## Element Selection

On the Backup page, elements are shown in a collapsible grid with checkboxes.
The header shows `▶ Backup Elements (33/33 selected)`.

- Click an element's **ⓘ** icon for a description
- **Select All** / **Deselect All** buttons for quick toggling
- When **Global** level is checked, scope filters and elements are hidden (backs up everything)
