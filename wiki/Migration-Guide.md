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

> **The app keeps track of these steps for you.** The sidebar's **MIGRATION** section lists its pages in the order the work happens — validation (section 4) before moving the agents — and marks each one ✓ done, ● next, ! needs a look or … still running, with an *N of 9* bar and a card naming the next step. A strip above every migration page says which button does it — **Show me** lights the button up — and when a step finishes a toast hands you to the next one. A step still in progress shows *RUNNING*, never done. Before restoring without ✈ Pre-flight or 🔍 Preview, or migrating agents before validating, the app asks once. Progress is kept per SOURCE → DESTINATION pair and survives a restart; tick a step done elsewhere with **Mark done**, and use **All 9 steps → Start over…** for the next wave.

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

1. Navigate to **Restore to Dest** — step 1, the latest backup file loads automatically
2. Step 2 — set the restore scope; the line under the fields states exactly what will be restored
3. Click **⇄ Compare with destination…** to see every account, site and group of that scope beside what the destination already has: *✓ exists* is restored into the existing scope, *+ will be created* comes from the backup file, *≈ other case* is there under another spelling and *✕ skipped* won't be restored. Where a name differs, select it and pick the destination scope it really is (or type a new name), then **Rename N scopes in the backup**. If the destination has no accounts yet, the comparison — and the restore confirmation — say the restore will create everything from the backup file. See [[Restore#Compare with the Destination]]
4. Step 3 — click **▶ Restore N nodes**
5. After completion, click **📋 Restore report** to save a detailed HTML report

> The renames change the loaded backup only — not the file on disk, and nothing on the console. **More options → Rename in the backup** still takes a typed `Account/Site` path for the same edit.

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

### Step 4 — Migrate the Agents

Everything above moves *configuration*. This moves the **endpoints
themselves**, so that each source group's agents land in the same-named
group on the destination and inherit that group's policy.

> **Validate first (section 4).** Agents check in to whatever scope they
> are moved into, so it is much cheaper to fix the destination's
> structure before they arrive than afterwards.

Navigate to **Agent Migration**. It is one screen with three steps, top
to bottom. Each step's badge turns ✓ when it is done and ! when something
needs fixing, and the next thing to do is always the only filled button.

**1 · What to move** — the source accounts and sites to move (blank means
*everything*), and where they go:

- **Destination console** — the connected destination. Each source group
  lands in the destination group of the same name, in the account and
  site of the same name, with that group's own registration token (or
  its site's, when the group has none).
- **Site-token file** — for when nobody has API access to the
  destination; see [Moving Agents with a Site-Token File](#moving-agents-with-a-site-token-file).

The line under the step says in one sentence what will happen, or what is
missing, with a **Connections…** button when a console isn't connected.

> You don't need to know any ids. **Choose…** beside the account and
> site fields gives you a list to tick; leaving a field blank means
> *everything*. The site list is narrowed to whichever accounts you
> picked.
>
> On a large console the list shows the first 50 and says so — the
> console does the searching, so type part of a name to find the rest
> rather than scrolling. Anything you tick stays ticked while you keep
> searching, and the footer tells you how many are ticked but currently
> out of view. **All** and **None** apply only to what is on screen, so
> they can never silently select scopes you filtered away.

**2 · Check** — **Check what will move** reads both sides and lists every
source group beside the destination group it lands in, in the **Plan**
tab. **Nothing is sent.** Only the destination accounts whose names match
the source accounts in scope are read — and, when you name sites, only
the sites of those names — so moving one account out of sixty reads one
destination account, not sixty.

Read this list before going further: it is the answer to "did it find my
scopes, and where is each one going?". Filter it to **Will migrate**,
**Can't migrate** or **Already done**, and click a row for the whole
reason. Anything that cannot migrate says why:

| Reason | What to do |
|---|---|
| *group / site / account not on destination* | The name differs between the consoles. Open **Fix names** — see [Fixing names that differ](#fixing-names-that-differ). |
| *no registration token* | Neither the destination group nor its site has one. Create a token on the destination, then **Check again**. |
| *already migrated* | Nothing to do — those agents are on the destination already. |
| *cannot read agents* | The source token cannot list that group's agents; check `Agents.view`. |

The check is remembered: reopening the app restores it, with its age, as
long as it was made for the same two consoles. **Export plan** saves it
as a report.

**3 · Migrate** — the button names how many agents it is about to move,
and only the rows the check marked ready are sent — each group with its
own token, in batches of 1,000. Every machine is listed in the **Agents**
tab as it goes, with the console's own reason when one doesn't make it;
the **Failed** filter isolates those. **Schedule…** arms the same run for
a date and time instead — keep the app open and the machine awake.

Step 3 only ever runs the plan on screen:

- Change the accounts, sites or destination in step 1 and step 3 locks
  until you **Check again**.
- After a run it stays locked until you **Check again**, which shows what
  is left — failed or pending agents, or new ones — before anything else
  is sent. **Export results** keeps the run's record, even after the
  re-check.

### Fixing Names That Differ

**Fix names** shows your source scope as a tree — account › site ›
group, with agent counts — next to what the destination has in the
same place:

| Destination column | Meaning |
|---|---|
| ✓ same name | The destination has a scope with the same name here. Nothing to do. |
| ✕ not found | The destination has no scope with this name here. |
| · pair the site first | A group under a site that wasn't found. Its groups are compared once you pair the site. |
| → "Branch" | Your pick, applied when you check again. |
| ✎ "Branch" · fixed earlier | A fix you made earlier. |

Select a scope to see why it didn't pair. The panel lists every
destination scope in the same place (the destination account for a site,
the destination site for a group) and what each one already pairs with.
Closest names come first. A scope that already pairs with another source
scope is greyed out and can't be picked: a fix renames that destination
scope in the plan, which would take it away from its current pair. When
the same name exists elsewhere on the destination, such as a *Kiosks*
group in another site, the panel says so, because a scope only pairs
inside its own account or site.

**Needs a fix**, **All** and **Fixed** filter the tree, and the search box
matches source and destination names. The box above the destination list
filters it. You can also type an exact destination name there. A name
that wasn't in the destination read is marked *typed* and shows a
warning, so use it only when you know the destination has exactly that
name. When you pair a site, its groups are compared straight away.
**Fixed** lists earlier fixes, each with a **Remove this fix** button.

Nothing is sent from this window. **Apply & check again** saves your
picks and runs the check again. The **Plan** then shows each fixed scope
under the destination's own name. Fixes are stored per account and site,
and re-applied every time the destination is read again.

### Moving Agents with a Site-Token File

Sometimes the destination belongs to a partner and nobody has API access
to it. They send a sheet with each new site's name and registration token
instead (*Site Name / Site Token*) — that is enough to migrate:

1. In step 1 choose **Into: Site-token file**, then **Load file…** (CSV,
   TSV or Excel) or **Paste** the two columns straight from Excel or an
   e-mail. A destination map saved earlier (`.json`) loads too.
2. **Check what will move** pairs every source site with the row of the
   file that names it. Its agents move with that row's token.
3. **Migrate** as usual.

Nothing is guessed, because a wrong guess sends one customer's agents
into another customer's site:

- A name must match exactly, ignoring case and spacing. A name that would
  match in more than one place is refused.
- A token for the **source** console itself is refused — nothing would
  move.
- Every row is checked before any console is asked, and every row that
  can't be used says why. **View rows** lists the whole file, showing only
  enough of each token to tell two apart.
- When the file spells a site differently — `shira-telecom` for
  *Shira Telecom* — the plan says so (*Row 4 of the file,
  'shira-telecom', is the same name spelt differently*) and step 2 shows
  **✎ Pair sites**. It lists each source site the file doesn't name
  beside the rows of the file no site uses, closest name first — also
  when you chose one site in step 1, where the file's other rows aren't
  otherwise checked. The same name spelt differently is selected for a
  look, but nothing is paired until you click **Use row N**; a row's
  token goes to one site only. **Pair & check again** re-runs step 2 with
  your choices, and the agents land where that row says. The file on
  disk is left as it is.

### What to Expect After the Move

| Result | Meaning |
|---|---|
| **moved** | Confirmed on the destination console. |
| **pending** | The console accepted it, but the agent hasn't checked in yet — it moves on its next connection. Offline machines sit here. |
| **failed** | The console rejected it, or reports the migration as failed. The row carries the reason. |

`move-to-console` only replies with a count, so the page reads each agent
back to produce the per-machine result above. Turning **Confirm each
agent arrived** off halves the API calls, but then "moved" means only
that the console accepted the request.

Run the **Status report** tab later to confirm that the pending agents
arrived.

---

## 4. Post-Migration Validation

### Built-in Migration Validation (v1.4.0+)

S1 Command Center includes a dedicated **MIGRATION** tab that compares the live source console against the live destination in real time:

- Matches accounts, sites, and groups by name (rename-aware via mangle)
- Diffs every config element by **count** and by **item name** — policy, exclusions, blocklist, firewall rules/locations, device control, network quarantine, saved filters, config overrides
- Shows a compact per-node summary with exact missing/extra item names
- **Export Report** generates an HTML document listing every differing item with a "why" and "what to do" for each

### Manual Validation Checklist

1. **Review the Restore Report** — click **📋 Restore report** after restore and check for:
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
