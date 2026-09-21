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
| `Tags.view` | Reading firewall / network-quarantine / device-inventory tags |
| `Tag Management.view` | Reading unified endpoint tags (`GET /agents/tags`) |
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
| `Tags.create` | Creating firewall / network-quarantine / device-inventory tags |
| `Tag Management.create` | Creating unified endpoint tags (`POST /tag-manager`) |
| `ThreatIntelligence.create` | Creating IOCs |

> **Endpoint tags need their own permission.** `Tags.create` does *not* cover
> the Tag Manager route that unified endpoint tags are created through. A
> token with only `Tags.create` can restore firewall tags and still leave the
> destination's endpoint tag list empty.

### Agent Migration

Moving the agents is separate from restoring the configuration, and the
two consoles need different things.

| Console | Permission | Required For |
|---------|-----------|-------------|
| DESTINATION | `Accounts.view`, `Sites.view`, `Groups.view` | Reading the destination's scopes **and their `registrationToken`** into the map file (step 1) |
| SOURCE | `Agents.view` | Listing each group's agents, and reading them back afterwards to confirm each one moved |
| SOURCE | `Agents.actions` | Issuing the move itself (`POST /agents/actions/move-to-console`) |

> **A scope with no registration token cannot receive agents.** If the
> map file shows `MISSING` for a site and its groups, create a token on
> the destination console and read the destination again — step 2 will
> otherwise mark everything under it as unable to migrate.

> **`Agents.view` alone looks like it works.** Matching (step 2) only
> reads, so it succeeds on a view-only token; the move in step 3 is then
> rejected per batch and every agent in it is reported failed with the
> console's reason.

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
