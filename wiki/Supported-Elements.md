# Supported Elements

S1 Command Center supports 26 configuration element types for backup and restore.

## Element Table

| # | Element | Backup | Restore | Scope | Notes |
|---|---------|:------:|:-------:|-------|-------|
| 1 | **Policy** | ✅ | ✅ | All | Full policy configuration |
| 2 | **Exclusions** | ✅ | ✅ | All | All 5 types: hash, path, file type, certificate, browser |
| 3 | **Blocklist** | ✅ | ✅ | All | SHA1/SHA256 hash restrictions |
| 4 | **Firewall Rules** | ✅ | ✅ | All | With rule ordering preserved |
| 5 | **Firewall Config** | ✅ | ✅ | All | Enabled, inheritance, location-aware |
| 6 | **NQ Config** | ✅ | ✅ | All | Network Quarantine configuration |
| 7 | **NQ Rules** | ✅ | ✅ | All | Network Quarantine allow-rules |
| 8 | **Device Control Rules** | ✅ | ✅ | All | USB, Bluetooth block/allow |
| 9 | **Device Control Config** | ✅ | ✅ | All | Enabled, reporting settings |
| 10 | **Tags (Firewall)** | ✅ | ✅ | All | Firewall rule classification tags |
| 11 | **Tags (NQ)** | ✅ | ✅ | All | Network quarantine tags |
| 12 | **Tags (Endpoint)** | ✅ | ✅ | All | Device inventory and unified tags |
| 13 | **STAR Rules** | ✅ | ✅ | Account, Site | S1QL custom detection rules |
| 14 | **Saved Filters** | ✅ | ✅ | Account, Site | Deep Visibility saved queries |
| 15 | **Threat Intel** | ✅ | ✅ | Account | IOC indicators (batched, up to 5000) |
| 16 | **Config Overrides** | ✅ | ✅ | All | Persistent agent config overrides |
| 17 | **Log Collection Rules** | ✅ | ✅ | Account, Site | XDR log ingestion rules |
| 18 | **Auto-upgrade Policies** | ✅ | ✅ | Account, Site | Agent upgrade schedules |
| 19 | **Notification Settings** | ✅ | ✅ | Account, Site, Global | Alert notification config |
| 20 | **SSO Settings** | ✅ | ✅ | Account, Site, Global | SAML single sign-on |
| 21 | **SMTP Settings** | ✅ | ✅ | Account, Site, Global | Email relay settings |
| 22 | **Syslog Settings** | ✅ | ✅ | Account, Site, Global | Syslog forwarding |
| 23 | **AD Settings** | ✅ | ✅ | Account, Site, Global | Active Directory integration |
| 24 | **Roles** | ✅ | ✅ | Account | RBAC custom role definitions |
| 25 | **Service Users** | ✅ | ✅ | Account | API service accounts |
| 26 | **Gateways** | ✅ | ✅ | Account, Site | Management proxy configurations |

## Scope Legend

| Scope | Meaning |
|-------|---------|
| **All** | Global, Account, Site, and Group levels |
| **Account, Site** | Account and Site levels only |
| **Account** | Account level only |
| **Account, Site, Global** | Settings that exist at account, site, or global level |

## Element Selection

On the Backup page, elements are shown in a collapsible grid with checkboxes. The header shows `▶ Backup Elements (26/26 selected)`.

- Click an element's **ⓘ** icon for a description
- **Select All** / **Deselect All** buttons for quick toggling
- When **Global** level is checked, scope filters and elements are hidden (backs up everything)
