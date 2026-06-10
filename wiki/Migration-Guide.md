# Migration Guide

A complete step-by-step guide for migrating SentinelOne console configurations (Dynamic Groups, Saved Filters, policies, exclusions, and all 26 element types) from a source tenant to a destination tenant using S1 Command Center.

---

## 1. Accessing S1 Command Center

**Download the pre-built app** from the [Releases page](https://github.com/s1community/s1-command-center/releases/latest):

| Platform | Download |
|----------|----------|
| **macOS** | `S1-Command-Center-macOS.dmg` |
| **Windows** | `S1-Command-Center-Windows-Setup.exe` (installer) or portable ZIP |

### macOS — One-line Install (Recommended)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
```

This downloads the latest DMG, copies the app to `/Applications`, strips the macOS quarantine flag, and launches it — no Gatekeeper prompts.

### Run from Source (Any Platform)

Requires **Python 3.10+**.

```bash
git clone https://github.com/s1community/s1-command-center.git
cd s1-command-center
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## 2. Required Permissions & Roles

> **Recommendation:** Use a **Service User with Admin role** on both SOURCE and DESTINATION consoles, scoped at **Global** level.

**Token creation path:** S1 Console → **Settings → Users → Service Users → Generate API Token**

### Backup Permissions (Read — SOURCE)

| Permission | Purpose |
|---|---|
| `Accounts.view` | Read account structure |
| `Sites.view` | Read site structure |
| `Groups.view` | Read group structure |
| `Policy.view` | Read policies |
| `Exclusions.view` | Read exclusions |
| `Restrictions.view` | Read blocklist |
| `Firewall.view` | Read firewall rules/config |
| `DeviceControl.view` | Read device control |
| `STAR.view` | Read custom detection rules |
| `Settings.view` | Read settings |
| `Tags.view` | Read tags |
| `ThreatIntelligence.view` | Read IOCs |

### Restore Permissions (Write — DESTINATION)

| Permission | Purpose |
|---|---|
| `Sites.create` | Create missing sites |
| `Groups.create`, `Groups.edit` | Create and reorder groups |
| `Policy.edit` | Write policies |
| `Exclusions.create` | Create exclusions |
| `Restrictions.create` | Create blocklist entries |
| `Firewall.create` | Create firewall rules |
| `DeviceControl.edit` | Write device control |
| `STAR.create` | Create custom detection rules |
| `Settings.edit` | Write settings |
| `Tags.create` | Create tags |
| `ThreatIntelligence.create` | Create IOCs |

For a complete permission reference, see [[API Token Permissions]].

---

## 3. Migration Procedure

### Step 1 — Connect Consoles

1. Launch the app → go to **Connections**
2. Fill in the **SOURCE** console (Name, URL, API Token) → click **Save & Connect**
3. Fill in the **DESTINATION** console (Name, URL, API Token) → click **Save & Connect**
4. Both consoles appear in the sidebar with connection status indicators

> **Pro Tip:** Copy a migration ticket to your clipboard and click **Paste from Ticket** to auto-fill all fields across all pages (connections, backup filters, restore filters, and mangle rename).

### Step 2 — Backup the Source Console

1. Navigate to **Backup Source**
2. Select levels to backup: **Accounts**, **Sites**, **Groups**
3. Optionally filter by account, site, or group name (substring match, case-insensitive)
4. Verify that all needed elements are checked — especially **Saved Filters** (required for Dynamic Group filter migration) and **Group Ranking**
5. Click **▶ Start Backup**
6. Save the JSON backup file when prompted

The backup captures all 26 element types, including:
- **Saved Filters** (Deep Visibility saved queries) per account/site
- **Dynamic Groups** with their `filterName` back-filled from the source console
- **Group Ranking** (priority order per site)
- Policies, exclusions, blocklist, firewall rules, STAR rules, tags, device control, and more

### Step 3 — Restore to the Destination Console

1. Navigate to **Restore to Dest** — the latest backup file loads automatically
2. Set restore scope and filters
3. If source and destination account/site names differ, use **Mangle Rename** to map them
4. Click **▶ Restore Now**
5. After completion, click **Export Log** to save a detailed HTML report

### What Happens During Restore (Automatic)

| Scenario | Handling |
|---|---|
| **Missing accounts/sites/groups** | Auto-created on the destination |
| **Dynamic Groups** | Source filter name is resolved to the destination's matching saved-filter ID and bound to the group |
| **Pinned Groups** | Created as pinned type on the destination |
| **Saved Filters** | Matched by name; duplicates are skipped |
| **Duplicate items** | Detected and skipped (exclusions, blocklist, STAR rules, filters, firewall rules, tags) |
| **SKU mismatch** | Prompts to auto-fix license bundle references (e.g. Core → Complete) |
| **Expired STAR rules** | Auto-extended to 1 year from now |
| **Expired/deleted sites** | Automatically skipped |
| **Group Ranking** | Restored as the final step, preserving group priority order per site |

### Restore Order

Elements are restored in this sequence for each node:

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
16. **Group ranking** (last)

---

## 4. Post-Migration Validation

### Built-in Migration Validation (v1.4.0+)

S1 Command Center includes a dedicated **MIGRATION** tab that compares the live source console against the live destination in real time:

- Matches accounts, sites, and groups by name (rename-aware via mangle)
- Diffs every config element by **count** and by **item name** — policy, exclusions, blocklist, firewall rules/locations, device control, network quarantine, saved filters, config overrides
- Shows a compact per-node summary with exact missing/extra item names
- **Export Report** generates an HTML document listing every differing item with a "why" and "what to do" for each

### Manual Validation Checklist

1. **Review the Restore Report** — click **Export Log** after restore and check for:
   - Summary statistics (nodes restored, skipped, errors, elements created)
   - The **Failed Items Table** listing every un-restored item with its name, value, and exact API error
   - Errors & warnings section
2. **Run the Migration Validation page** for a live diff between source and destination
3. **Spot-check on the destination console:**
   - Verify dynamic groups show the correct filter binding
   - Verify saved filters exist and return expected results
   - Confirm policy settings match the source
   - Check exclusion and blocklist counts match
   - Verify STAR rules are active and not expired
   - Confirm firewall and device control rules are present

---

## 5. Group Ranking — Review & Validation

Group ranking (priority order) is the **last step** in the restore sequence. To validate:

1. **Check the restore report** — look for the "Group Ranking" row in each site's node summary to confirm it was applied successfully
2. **Open each site on the destination console** → navigate to **Groups** → verify the group order matches the source
3. If group ranking was skipped or shows an error in the report, you can:
   - Re-run a targeted restore for just that site with only the **Group Ranking** element checked
   - Manually reorder groups in the destination console UI
4. Use the **Migration Validation page** to diff the group structure between source and destination

---

## 6. Known Limitations & Prerequisites

| Limitation | Detail |
|---|---|
| **Global-scoped tokens required** | Account-scoped tokens may miss cross-account elements. Use Global-scoped Service User tokens on both consoles. |
| **Firewall rule locations** | Cross-console location bindings may not transfer — rules are retried as location-agnostic with a warning to re-attach locations manually. |
| **Inherited settings** | Scopes that inherit settings from a parent cannot be modified directly. Decouple inheritance on the destination first if needed. |
| **Threat Intel** | Batched up to 5,000 IOCs per account. |
| **STAR rules scope** | Supported at Account and Site level only (not Group). |
| **Saved Filters scope** | Supported at Account and Site level only. |
| **Dynamic → Static group drift** | If the source has a dynamic group and the destination already has a static group with the same name, the restore overwrites the destination group's `filterId` to make it dynamic. |
| **Expired/deleted sites** | Automatically skipped during restore. |
| **Unicode in exclusion paths** | Invisible characters (LTR marks, zero-width joiners, BOMs) are auto-scrubbed. |

---

## 7. Additional Resources

| Resource | Link |
|---|---|
| **GitHub Releases** | [Download Latest](https://github.com/s1community/s1-command-center/releases/latest) |
| **Full Wiki** | [S1 Command Center Wiki](https://github.com/s1community/s1-command-center/wiki) |
| **Quick Start** | [[Quick Start]] |
| **Backup Guide** | [[Backup]] |
| **Restore Guide** | [[Restore]] |
| **Supported Elements (26)** | [[Supported Elements]] |
| **API Token Permissions** | [[API Token Permissions]] |
| **Troubleshooting** | [[Troubleshooting]] |
| **Changelog** | [[Changelog]] |
