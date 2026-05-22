# API Token Permissions

## Creating the Token

1. Go to the S1 console: **Settings → Users → Service Users**
2. Click **Generate API Token**
3. Scope it to the minimum permissions needed

> **Recommendation:** Use a Service User with **Admin** role for full backup/restore access.

## Minimum Permissions

### Backup (Read)

| Permission | Required For |
|-----------|-------------|
| `Accounts.view` | Reading account structure |
| `Sites.view` | Reading site structure |
| `Groups.view` | Reading group structure |
| `Policy.view` | Reading policies |
| `Exclusions.view` | Reading exclusions |
| `Restrictions.view` | Reading blocklist |
| `Firewall.view` | Reading firewall rules/config |
| `DeviceControl.view` | Reading device control |
| `STAR.view` | Reading custom detection rules |
| `Settings.view` | Reading settings |
| `Tags.view` | Reading tags |
| `ThreatIntelligence.view` | Reading IOCs |

### Restore (Write)

| Permission | Required For |
|-----------|-------------|
| `Sites.create` | Creating missing sites |
| `Groups.create`, `Groups.edit` | Creating/reordering groups |
| `Policy.edit` | Writing policies |
| `Exclusions.create` | Creating exclusions |
| `Restrictions.create` | Creating blocklist entries |
| `Firewall.create` | Creating firewall rules |
| `DeviceControl.edit` | Writing device control |
| `STAR.create` | Creating custom rules |
| `Settings.edit` | Writing settings |
| `Tags.create` | Creating tags |
| `ThreatIntelligence.create` | Creating IOCs |

### Operations Pages

| Permission | Page |
|-----------|------|
| `Agents.view`, `Agents.actions` | Agents (list, scan, uninstall) |
| `Threats.view` | Threats |
| `Activities.view` | Activities |
| `Applications.view` | Apps & CVEs |
| `Ranger.view` | Ranger & Rogues |
| `RemoteScripts.view` | Remote Scripts |
| `Users.view`, `Users.create` | Users & Roles |

### Purple AI & Unified Alerts

| Permission | Feature |
|-----------|---------|
| Purple AI entitlement | Purple AI page |
| Alert read/write | Unified Alerts page |

## Token Scope

Tokens can be scoped to:
- **Global** — Access to all accounts, sites, groups
- **Account** — Limited to a specific account and its children
- **Site** — Limited to a specific site

For migration work, a **Global-scoped** token is recommended on both SOURCE and DESTINATION.
