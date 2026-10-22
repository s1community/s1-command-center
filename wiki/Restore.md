# Restore

The Restore page pushes backup data to the DESTINATION console, recreating the entire configuration hierarchy.

## Workflow

The screen is three numbered steps, top to bottom. Each step's badge turns **✓** when it is done and **!** when something needs fixing, and the next thing to do is the only filled button.

1. **Backup file** — Auto-loads the latest backup, or **Browse…** (or paste a path and press Enter). The line underneath says what the file holds, e.g. `1 account · 2 sites · 4 groups · from fao.sentinelone.net`. **↩ Rollback** loads the last pre-restore snapshot instead — see [Snapshot & Rollback](#snapshot--rollback)
2. **What to restore** — Leave the fields blank for everything, or name accounts, sites or groups — see [Restore Scope](#restore-scope). A live line states exactly what will be restored. **⇄ Compare with destination…** shows every account, site and group of that scope beside what the destination already has, and lets you rename backup scopes to match — see [Compare with the Destination](#compare-with-the-destination). **More options** holds the element choices, [Rename in the backup](#rename-in-the-backup) and [Defaults & licenses](#defaults--licenses-dialog)
3. **Restore** — **▶ Restore N nodes** resolves the structure, then pushes config node by node. **✈ Pre-flight** and **🔍 Preview changes** check first without writing anything

While a restore runs, only **■ Stop** and **⏭ Skip** are offered. When it finishes, step 3 shows the results buttons — see [Export Report](#export-report) — and **↻ Resume (N left)** if it was stopped or nodes failed.

### Unattended

The **⚡ Unattended** switch beside the Restore button runs without stopping to ask: missing accounts are created and every prompt is answered automatically. You still confirm once — the confirmation names the scope and says the run is unattended. **Resume** always runs unattended, after its own confirmation.

## Auto-load

If a backup was just completed, the file path carries over automatically. Otherwise the newest backup found nearby (home, Desktop, Downloads, Documents and the app's folder) is loaded. Restore reports and other JSON files that aren't backups are passed over.

Picking one of those by hand doesn't fail with a Python error any more: the line under the file says *"This is a restore report, not a backup"* (or *"This file isn't a backup"*, *"…isn't valid JSON"*), and Restore stays off.

## Defaults & Licenses Dialog

**More options → ⚙ Defaults & licenses…** opens a table editor for the backup file. Editable fields per account/site/group:

| Field | Type | Purpose |
|-------|------|---------|
| `isDefault` | Checkbox | Mark as default site |
| `expiration` | Text | License expiration date |
| `unlimitedExpiration` | Checkbox | Never expire |
| `unlimitedLicenses` | Checkbox | Unlimited agent licenses |

Bulk buttons: **∞ Exp ON/OFF**, **∞ Lic ON/OFF** to set all at once.

## Restore Scope

The **Levels** boxes (Accounts, Sites, Groups, Global settings) pick which kinds of node are restored; the **Account / Site / Group** fields narrow them by name. Leave the fields blank to restore everything at the ticked levels.

- **Site** takes one site or several, comma-separated: `FAO-TEST, FAO-TEST-2`. Double-quote a name that contains a comma: `"Paris, France", Rome`.
- **Choose…** next to the Site field lists the sites in the loaded backup, with their account and group count, so you can tick them instead of typing. Ticking none means every site.
- Naming a site restores **that site and its groups only**. With **Accounts** ticked, the account that holds it is restored too. No other site or account is resolved, listed or written.
- **Group** narrows inside the chosen sites. On its own, it brings only the site(s) and account that hold that group.
- **Group ranking** re-orders only the chosen sites' groups.
- A name that isn't in the backup is flagged in red under the fields as you type, with the names the backup does have, and Restore stays off — nothing is written.
- **Global settings** hides the fields and ignores them.
- Unticked elements (More options) are counted on the same line: `… · 12 of 33 elements`.

The line under the fields, the confirmation and the log all state the same scope, e.g. `Site: FAO-TEST · with its account: FAO — 4 of 179 backup node(s)`, and the Restore button carries the count. Restore, Unattended, Resume and Preview all use that scope.

## Results

Under the steps, two tabs share the space:

- **Progress** — a card per site, plus one for the account and one for global settings when they are restored. Each card has a badge (the site's number, then ✓ when it's done or ! when something failed), a done/total count and a small bar. Its groups are numbered 1, 2, 3 inside it, and the line above the bar names both: *Restoring site 3 of 4 · FAO-ROME — group 2 of 3: Servers*. The strip on top totals the run and holds **Fold all** and, when something failed, **Show failed only**. Click a card to fold or unfold it; a run of more than 14 nodes starts folded and opens the card that is running or has failed. Hover a row for its full path, its number in the backup (as in the other tab's node list) and the whole message. Nodes a Resume passes over because they already finished show as done.
- **Backup vs destination** — pick a node to compare what the backup holds with what the destination has now. **Preview changes** and the restore itself fill in the destination side, and Preview switches to this tab when it finishes.

The tabs keep working while a restore runs. They are hidden while **More options** is open, to give the options the room; starting a restore or a preview brings them back.

## Compare with the Destination

The restore finds accounts, sites and groups on the destination by their **exact** name: a backup scope with a twin there is restored into it, and one without is created from the backup file. **⇄ Compare with destination…** (step 2) shows that before anything is written. It reads the destination — its accounts, and the sites and groups of every account a backup account could land in — and opens a window with two panes.

**Left: the tree.** What this restore touches, account › site › group, beside what the destination has in the same place. Scopes that are only shown because something under them is restored say so. *Items* counts the settings each scope carries in the backup.

| Mark | Meaning |
|------|---------|
| ✓ exists | The destination has it by that exact name — the backup's settings are restored into it |
| + will be created | Not on the destination — created from the backup file |
| ≈ other case | There under another case or spacing (`acme corp` vs `Acme Corp`). The exact-name restore would miss it and try to create a near-duplicate |
| → | You renamed it — into an existing scope, or to a new name it is created under |
| ✕ skipped | Not restored, and nor is anything under it: its name is held by an expired or deleted account, its parent won't exist, or its level isn't ticked in step 2 |

**Needs a look** (the opening filter when there is something to look at) keeps the near matches, the skipped scopes and the scopes that would be created beside others — with the scopes above them for context. **All** shows everything; **Renamed** shows your renames. The search box matches backup and destination names.

**Right: the selected scope.** Why it is restored into something, created or skipped, in a sentence or two; every destination scope in its place, closest name first, with the backup scope already restoring into each; where else on the destination its name turns up; and what the restore will ask when it gets there — for example that it will offer to put a new site on the account's default site, and to answer No when another backup site already restores into that one.

**Renaming.** Pick a destination scope and **Restore into “…”** to rename the backup scope to it, or type a new name and **Rename to “…”** to have it created under that name. A name another backup scope in the same place already uses is refused — two scopes would merge in the backup — and so is a name with `/`. Renaming an account or site resets the renames under it, because its children are then compared with a different place. Picking a destination account that wasn't read yet reads its sites and groups in the background.

**Apply.** **Rename N scopes in the backup** renames them in the loaded backup the way [Rename in the backup](#rename-in-the-backup) does (parents first), points the Account / Site / Group fields at the new names, and logs each rename. The file on disk is left as it is, and nothing is sent to the console. The line beside the button then says what was renamed; compare again to check.

**When the destination has nothing.** If the destination has no accounts, the window and the line beside the button say so: *The DESTINATION console has no accounts yet — this restore will create everything from the backup file: 2 accounts, 4 sites, 8 groups.* When it has accounts but none of this restore's, the line says *Nothing in this restore is on the DESTINATION console yet — it will create all of it from the backup file*. The Restore confirmation says the same instead of *This will OVERWRITE settings*. A destination that couldn't be read is reported as *Couldn't read the DESTINATION console* — never as empty.

A few more things it accounts for:

- **Ticket account ID** — after **Paste from Ticket**, accounts and sites go to the ticket's account whatever their name, but groups look their account up by name; the window shows that and suggests renaming the account to match.
- **Scope changes** — change the fields, levels or console afterwards and the line asks you to compare again.
- **Global settings only** — nothing to compare; the line says so without reading the console.

## Rename in the Backup

**More options → Rename in the backup** (the CLI's *mangle rename*) renames account/site/group paths in the loaded backup before restoring:

| Source (from backup) | Destination (on target) |
|---------------------|------------------------|
| `OldCorp/Production` | `NewCorp/Production` |
| `OldCorp` | `NewCorp` |

The fields are auto-filled when you use **Paste from Ticket**. If none of the backup's accounts exists on the destination, the restore asks first and can open [Compare with the Destination](#compare-with-the-destination) for you, to rename the account (and anything else) before restoring.

## Snapshot & Rollback

With **📸 Snapshot first** ticked (the default), a restore first saves the destination's current settings for the same scope and elements. **↩ Rollback** in step 1 loads the latest snapshot as the backup; restore it to put the destination back the way it was.

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

Same site-by-site view as Backup — see [[Backup#Progress Table]].

Each node shows a detailed summary: `policy, excl:12, block:5, fw:3, star:8, …`

## Export Report

When a restore finishes, step 3 shows its results buttons: **📊 Full report**, **📋 Restore report**, **🛟 Explain errors** (only when something failed), and **🧩 Gap report** / **⬇ CSV** (item by item: what landed and what didn't).

**📊 Full report** — also offered by the pop-up at the end of a restore — is one interactive HTML file covering the whole migration in tabs: how the backup went, how the restore went, every failure with the fix, what landed, what is still missing, the pre-flight and preview, Migration Validation when it ran, and the next steps. A stopped-and-resumed restore is reported as one migration. See [[Reports#Full Migration Report (HTML)]].

Restore report formats:

- **HTML** — Professional dark-themed report (recommended)
- **JSON** — Structured data for automation
- **Excel** — Spreadsheet with all nodes and elements

See [[Reports]] for details.
