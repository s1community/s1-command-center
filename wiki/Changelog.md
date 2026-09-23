# Changelog

## v2.6.1 — 2026-09-23

### Added
- **Every report is now interactive.** The tables in the agent-migration reports (live run, status, match plan) *and* in the configuration **Restore Report** and **Migration Validation Report** now carry a filter box and click-to-sort columns. Type to narrow a table to the matching rows — the count shows "N of M" and an empty result says so — and click any header to sort it, numeric-aware, ascending then descending. It ships as inline vanilla JavaScript with no external assets, so the saved `.html` still opens offline and unchanged when it's emailed or attached to a ticket, and every untrusted value stays HTML-escaped. The agent reports render their own filter toolbar; the restore and validation reports only tag their tables, and the shared script builds the toolbar for them at load (skipping any table that already has one).
- **Open the report straight after export.** Saving any report now asks *"Open it now?"* and, if you agree, opens the file with the operating system's default handler — cross-platform (`open` on macOS, `os.startfile` on Windows, `xdg-open` on Linux).

### Tests
- 600 total (+4 since v2.6.0): the interactive markup, the shared script's auto-bootstrap of plain `.data-table` tables while it skips ones that already have a toolbar, and the open-after-export prompt. Filtering and sorting were additionally verified end-to-end in headless Chrome (typing a term hides the non-matching rows and the count updates to "N of M").

## v2.6.0 — 2026-09-23

### Added
- **A full HTML report for the agent migration, to match the one the configuration migration already had.** The restore has always exported a polished HTML Restore Report; the agent side only ever produced a flat table. All three agent exports — the **match plan**, the **live run** and the **status report** — now build the same kind of self-contained, dark-themed document: a header, stat cards, a source/destination info box, colour-coded status badges (moved / pending / failed / migrated / decommissioned), and one section per concern. The live-run report leads with a **Did not migrate — manual action required** table carrying the console's own reason per machine, then the errors, a per-group breakdown, and finally every agent; the match-plan report splits **Will migrate** from **Will not migrate** (with the reason) and **Already migrated**. The **Export** button on each panel now offers HTML (default), Excel, flat CSV and JSON from one place. Every untrusted value — computer names, usernames, error text — is HTML-escaped, so a hostile agent name cannot inject markup into the report.
- **The "Include passphrases" option now states what it costs, and asks first.** Fetching agent passphrases is a sensitive, audited action, and the switch used to describe it only as "one extra API call per agent". It now says plainly — in the field caption, in the live log when toggled on, and in a confirmation dialog before the run starts — that it is one API call per agent (slow on a large scope), that **SentinelOne records every passphrase fetch in the source console's activity log**, and that the exported file will contain secrets. A status report that actually carries passphrases prints a red banner at the top of the HTML repeating the warning, so whoever opens the file is told to treat it as sensitive and that the fetches were logged.

### Changed
- The generic table export (`export_utils.export_report`) is unchanged and still used elsewhere; the agent migration now routes through a new `export_agent_report` that renders the structured report. The report itself is built by plain functions (`build_live_report` / `build_status_report` / `build_match_report`) on plain dicts, so it is produced and tested without a console or a window.

### Tests
- 596 total, up from 584. New `tests/test_agent_report.py` covers the three builders (the failure/error/per-group/agent sections, the verification and stopped notes, the ready-vs-blocked split), the HTML generator (stat cards, status badges, the passphrase danger banner, and that untrusted values are escaped rather than rendered), the flat-CSV writer, and a source guard asserting the passphrase option warns about the activity log in the caption, the toggle and the run confirmation.

## v2.5.0 — 2026-09-21

### Added
- **Agent Migration — the endpoints themselves, not just the configuration.** Everything the tool did until now rebuilt a destination console and then stopped at the thing the customer actually counts: the agents. Moving them by hand means reading a registration token out of one console, selecting the matching endpoints in the other, and repeating that per group — for hundreds of groups, with no record of what landed. The new **Agent Migration** page does it as a guided three-step flow, each step unlocking the next:
  - **1 · Read destination** — walks the destination's accounts, sites and groups and saves them, with their registration tokens, to a map file.
  - **2 · Match scopes** — lists every one of your source scopes beside the destination scope it pairs with, by name. **Nothing is sent.** There is no dry-run switch to forget to tick, because this step physically cannot move an agent. Anything that can't migrate says why — a name that differs between the consoles, a missing registration token, agents that already moved — and a name mismatch gets a one-click **Fix name**.
  - **3 · Migrate** — sends the move per group with that group's own token, and names **every machine as it goes**, with the console's own reason when one doesn't make it.
- **Every agent is confirmed individually.** `move-to-console` answers with a **count** and nothing else, so "the console accepted 400" is not evidence that 400 machines arrived. Each agent in an accepted batch is now read back and reported as *moved*, *pending* or *failed* on its own. Offline endpoints are named as offline rather than counted as successes, and a rejected batch marks every agent in it failed with the console's error text instead of leaving the group looking done.
- **Scopes are picked from a list, not typed as ids.** **Choose…** on every account and site field opens a searchable, tickable list. The search runs **on the console**, one bounded page at a time, so a tenant with thousands of sites opens as fast as one with five. Ticks survive searching, the site list is narrowed to whichever accounts you picked, and ticking nothing means "everything".
- **Accounts missing on the destination are created during the restore.** `POST /accounts` requires every licence bundle to carry `surfaces` — a bundle sent as `{"name": "complete"}` is rejected with *"licenses: bundles: 0: surfaces: Missing data for required field"* — while `GET /accounts` hands back read-only extras on each bundle (`displayName`, `totalSurfaces`, `minorVersion`) that the create schema refuses. The licences block is now rebuilt field by field from the source account, falling back to the destination's own SKU when those licences don't exist on that tenant. The account is then **read back** rather than assumed created, and a name already held by an *expired or deleted* account — invisible to the normal listing, which filters to active — is surfaced as the cause instead of an unexplained rejection.
- **Pre-flight knows whether this console will create accounts at all.** `POST /accounts` needs Global permissions **and** an MSSP deployment; a non-MSSP console refuses it with `403 code 4030010` no matter how privileged the token is. Pre-flight now reports how many accounts the backup needs, whether the destination allows creating them, and says to map them onto existing accounts when it won't. **Diagnose account creation** reports who the token belongs to and what the console answers, so a permissions problem is not mistaken for a tool defect.

### Bug Fixes
- **A large restore looked frozen, twice over.** The before/after diff read **every element of every node, twice** — roughly 15,000 API calls on a big migration — to fill a panel that only needs the node's identity; those snapshots are now identity-only. Separately, `CTkOptionMenu` builds one Tk menu entry per value, so a backup with hundreds of nodes stalled the UI for seconds just *populating the node dropdown*. The dropdown is capped and says how many more there are; the restore still walks every node.
- **A failing account no longer buries its own cause.** An account that can't be created meant every site and group beneath it failed too, producing hundreds of errors with the real reason somewhere near the top. The run now stops at that account and shows the console's actual words.
- **An RBAC role that grants nothing is no longer posted.** When the destination template is unavailable there is no permission tree to send, and S1 refuses the result outright (*"You must have at least one permission configured"*, code 4000010). The retry that dropped rejected fields could only ever produce that same empty role, so it no longer pretends: the run says what actually went wrong.
- **Roles said nothing when there were none** — reported by DJ Wilhelm against 2.3.2. Every other element reports an empty result; roles produced no log line at all, so an account node with no captured roles looked exactly like a restore that had silently skipped RBAC.

### Changed
- **Scope listings are cached for the duration of a restore.** Resolving hundreds of nodes re-fetched the same accounts/sites/groups lists every time. The cache is opt-in and caller-scoped — a restore turns it on for its run and invalidates the matching kind whenever it creates a scope — so backups and inventory reads always hit the live console.
- The match plan from step 2 is cached against the consoles and scopes it was built for, so reopening the app doesn't re-walk the destination; its age is shown next to a **Match again** button, and any change to the inputs invalidates it. Registration tokens are stripped before the plan is written to disk and re-derived from the map on load.

### Tests
- 584 total, up from 440. The agent-migration suite pins the parts that are easy to regress invisibly: that no widget is created per agent and the live feed's rows are reused, that a per-agent result comes from a read-back rather than the batch count, multi-site id handling, chooser semantics (cancel is not "select none"), and the plan cache's fingerprint and token stripping.

## v2.3.2 — 2026-09-14

### Bug Fixes
- **Every config override was rejected, at every scope** — the Landeshauptstadt München restore (2026-08-24, 109 nodes) failed all 28 of them: 12 with `filter: siteIds: Unknown field`, 4 with `filter: groupIds: Unknown field`, and 12 at the account with `Internal server error (code 5000010)`. One cause behind all three. **`POST /config-override` takes no scope filter at all** — the `filter` on that endpoint selects *agents*, so every scope key we could put in it (`accountIds`, `siteIds`, `groupIds`) is an unknown field. The scope belongs inside the override body: `scope` plus a nested `{"site": {"id": …}}` / `{"group": {"id": …}}` reference naming the destination. v2.2.7 removed the source console's nested scope objects from that body, correctly — they carried the source tenant's ids, which is what the destination was 500ing on — but the filter was the only thing left binding the override to anything, and the filter was never valid. The create now sends `data` alone, with the **resolved destination** site/group id in it. An override is only ever bound to the node that owns it, so the account pass cannot stamp its id onto a group override the descendant query returned. Verified field-for-field against a known-good implementation of this endpoint rather than guessed at.
- **The error explainer described the wrong problem** — `filter: accountIds: Unknown field` had its own entry saying the scope travels in the body (right) and that the restore retries without the rejected key (which could only ever have created the override at the wrong scope, silently). It now covers all three keys, is scoped to config overrides so it cannot steal the Locations case — where the same message genuinely means "this element doesn't exist at group scope" — and the 500 entry names the source-id cause instead of implying a server fault.

### Tests
- 12 new: the destination site/group id is bound per scope, a numeric id is stringified, a group override handed to the account node is never stamped with the account's id, global stays unbound, the API call carries no `filter`, both explainer paths, and a source guard so `create_config_override(scope, …)` cannot come back. 440 total.

## v2.3.1 — 2026-09-14

### Bug Fixes
- **Exclusion names did not survive the migration** — reported by DGS S.p.A. through case #01714638: *"the number of exclusions in the target console is correct, however for some of the migrated ones we do not see the Exclusion Name"*. The count was right and the names were gone, which is exactly what the restore order produced. `GET /exclusions` and `GET /unified-exclusions` return the **same objects** — on the Beijer Ref backup, 1525 legacy and 1526 unified, every legacy item matching a unified one on type + osType + value — but only the unified one carries `exclusionName`; the legacy create schema has no field for a name at all (`actions, description, inject, mode, osType, pathExclusionType, source, type, value`). Both elements ship ticked, and the legacy pass ran **first**, so every exclusion was created nameless, the unified create that followed was answered *"already exists"*, and the 513 of 1525 that had a name lost it silently. Unified now runs first and the legacy pass only creates what unified did not land — it remains the fallback for backups and destinations without unified exclusions, including when the unified create is refused outright.
- **Exclusions already sitting on the destination without a name are now named** — a re-run could never have repaired the tenants this already hit: the create is answered *"already exists"* and changes nothing. When the source names an exclusion the destination holds unnamed, the name is now applied with `PUT /unified-exclusions` (the only call that can), copying every other field from the destination's own copy so nothing else can change. A name somebody set on the destination is never overwritten, and a refused rename is logged against the item instead of failing it.

## v2.3.0 — 2026-09-14

Everything here comes from one restore report: **beijerrefab, 2026-09-02** — 252 nodes, 611 failures, 466 of them (76%) from four causes that had nothing to do with the customer's data.

### Added
- **Migration Gap Report** — the restore report answers *"did the run finish?"*. It never answered the question every operator asks next: *"I backed up 45 exclusions and 43 landed — **which** two are missing, and why?"*. The restore now writes one ledger row per **item** it touches (`node, scope, element, item, status, reason`) and **🧩 Gap Report** turns that into a tabbed HTML/Excel document — one tab per element, each split into what is on the destination and what is not, with the console's own reason against every miss. CSV export for spreadsheet triage sits next to it. An item that is *inherited from another scope* or an element the backup legitimately holds nothing for are counted separately from real gaps, because the API returns inherited rules and tags at **every** level and counting those would bury the genuine misses under thousands of phantom ones. The restore summary now ends with the number of items needing attention and points at the report.

### Bug Fixes
- **141 failures: a scope that inherits its config was told to change it** — *"Cannot change firewall settings while inheriting settings from parent (code 4000010)"*, plus the device-control and network-quarantine equivalents. The restore already skipped this for **groups**, on the assumption that only groups inherit. Sites inherit from their account just as groups inherit from their site, and 141 of the 252 nodes were sites. Two things changed: the skip now applies at **site** scope as well, and it is decided from the **payload** (`inheritSettings` / `inherits` / `inheritedFrom`) rather than the node type — a config the source only inherited is not a config to write, at any level. An inherited config is recorded as *skipped, inherited from parent* instead of failing, so the report no longer buries 141 real results under a non-problem.
- **159 failures: every scheduled report was rejected as incomplete** — `GET /report-tasks` returns `day`, `recipients` and `isTrend` as `null`, and `POST /report-tasks` refuses all three as null. Each one is now sent with the value that means "the source had none" (`[]`, `false`, and day 1 — only ever reached when the source task carries no day at all), and the run log names every field it had to fill in, per report. `fromDate` / `toDate` are deliberately **not** defaulted: they decide which period a report covers, and a report that looks migrated while covering the wrong dates is worse than one that is visibly missing — those few are explained and left for manual re-creation.
- **3 failures: RBAC roles were rejected by the destination's own template** — `GET /rbac/role` hands back a create-ready skeleton containing `pages`, and `POST /rbac/role` then answers *"data: dict_values(['pages']): Unknown field"*. Rather than guess what that console calls the field instead, the create is retried once **without the exact fields the error names**, and the run says loudly that the role was created without its permissions and needs them set by hand. A named role that is visibly incomplete beats no role at all.
- **166 failures made diagnosable** — all 150 endpoint tags and 16 config overrides died on the same opaque *"Internal server error (code 5000010)"*. Both now have their own entry in the error explainer: the endpoint-tag one points at **Operations → Inventory → Tags → Diagnose endpoint tags**, which writes one throwaway tag per candidate request shape and reads each back, so the console itself names the shape it stores; the override one states what was sent, that nothing in it is invented, and how to escalate. No payload was guessed at to make the error go away.

### Changed
- **A failed backup element now records why, in the file the customer sends.** Rows read `ERR 500: <the console's own words>` and `n/a (403: …)` instead of a bare `ERR` / `n/a`. The Landeshauptstadt München backup (2026-09-03) reported `upgrade-pol: ERR` on all 109 nodes and nothing more — the reason existed only in the live output console and was gone by the time the log was exported.
- **Gateways are declared unsupported, like webhooks before them.** `/gateways` was invented: it answered 404 on all 13 account and site nodes of that same backup, no backup has ever contained a gateway object, and gateways were never restored in the first place. Backup now reports `no API` instead of calling a route that cannot work and blaming the tool on every node. The element table in the README and the wiki said ✅ / ✅ for both gateways and webhooks; both rows are corrected.
- New guard tests: an inherited config is never written at any scope, scheduled-report defaults never overwrite a real value and never invent a data window, `_strip_unknown_fields` only ever removes fields the console actually named, the endpoint-tag and override 5xx explanations are not swallowed by the generic 5xx rule, `/gateways` cannot reappear as a string literal, and a backup failure row must carry its reason.

## v2.2.9 — 2026-09-04

### Bug Fixes
- **Group ranking came out scrambled while every write reported success** — reported on the Landeshauptstadt München migration (2026-09-02). Two faults stacked on top of each other:
  - **Ranks were applied one group at a time, in backup order.** SentinelOne renumbers a site's *other* groups on every rank write, so each of the 116 `PUT /groups/{id}` calls returned 200 and each one shifted the groups placed before it. The end state bore no relation to the source order. `rank` is no longer part of the per-group drift sync.
  - **The bulk reorder was sent a partial list and the failure was swallowed.** `PUT /groups/ranks` received only the groups matched by name, and an incomplete set of a site's dynamic groups makes the endpoint answer 500 — which went to the operation log and never to the restore report, so four failed sites read as a clean run.
  Ranking is now a single pass per site, after every group exists: it takes the site's **complete** set of destination dynamic groups (the endpoint is documented as dynamic-only — a static, pinned or Default group in the list is what breaks it), orders them by the source rank, applies the order, then **re-reads the console to verify it landed**. If the bulk call is rejected it falls back to per-group writes in ascending rank order, which converges instead of shuffling. The outcome is now a `group-ranks` row on the site's report, and a site that still doesn't match is marked as an error naming the groups.
- **Service users were never restored** — the element was on a "capture for reporting only" list, so ticking `service_users` created nothing, reported nothing, and left no row in the report. The API *token* genuinely cannot be migrated (SentinelOne reveals a token exactly once, at creation, so it is never in the backup) but the service user itself is creatable. Each one is now re-created with its name, description and scope, with `scopeRoles` rebuilt from **names** — the source's site and role IDs are meaningless on the destination. A scope that doesn't resolve is reported by name and the user is created at account scope rather than being sent a stale ID, and the run tells the operator to issue a fresh token for each user and update whatever integration used the old one.
- **Notification recipients failed on every scope of two consecutive migrations** — 43 of 43 beijerrefab scopes and the Landeshauptstadt München account, all with *"Bad Request :: Field data in request body must be valid class com.sentinelone.notification.preferences.rest.dto.NotificationRecipientDto"*: the console wants `data` to be **one** recipient, not a list. A per-recipient fallback already existed and would have worked, but it was gated on the error text containing "unknown field", which this message does not. Any `400` from the bulk PUT now reaches the fallbacks, so the recipients that can be migrated get through and the ones that can't surface their own reason. A non-400 (e.g. a `403`) is still raised untouched rather than retried.

### Changed
- Group ranking resolves each account's sites once instead of re-listing every account, site and group for every group node.
- The migration-scope deck moves service users to the "can be migrated" side, with the token caveat spelled out on the caveats slide.
- New guard tests: `/groups/ranks` is never sent a non-dynamic group, ranks are applied best-first and verified against the console, a failed ranking reaches the report, the per-group drift sync cannot start writing `rank` again, service-user payloads carry no source-side IDs or token metadata, and the recipients fallback is pinned against the exact error both consoles returned.

## v2.2.8 — 2026-09-02

### Bug Fixes
- **Four elements were never captured, and the backup reported no failure** — the Beijer Ref backup (2026-08-31, taken on 2.2.6 with all 33 elements selected) contained no `autoUpgradePolicies`, `logCollectionRules`, `webhooks` or `scheduledReports` on any of its 252 nodes. All four were requested against paths that do not exist in the v2.1 API, every call returned 404, and `_fetch` recorded a 404 as *"n/a"* — the same swallow that hid `/endpoint-tags` in 2.2.6. Nothing was wrong with the operator's element selection; the requests were simply addressed to nowhere.
  - Auto-upgrade policies: `/agents-policy/auto-upgrade-policies` → **`/upgrade-policy/policies`**
  - Log collection rules: `/log-collection-rules` → **`/log-collection/rules`**
  - Scheduled reports: `/reports/scheduled` → **`/report-tasks`** (`/reports` is the generated-report list; deletion is `POST /reports/delete-tasks`, there is no DELETE verb)
- **A 404 is no longer treated as "not applicable"** — a `403` means the console declined and is still *n/a*; a `404` means this tool asked for a path that isn't there, which is a defect in the tool and is now surfaced as an error with a note to report it. Folding the two together is precisely what allowed four elements to vanish for a whole migration without a single warning.
- **Auto-upgrade policies do not follow the API's normal shape** — the resource is scoped by `scopeLevel` + `scopeId` instead of the usual `accountIds`/`siteIds` filter, paginates on `skip`/`limit` instead of a cursor, and makes `osType`, `sortBy` and `sortOrder` mandatory. `get_all()` satisfied none of that, so even the corrected path would have returned 400. The client now issues one correctly-formed query per OS family (windows, linux, macOS) and merges the results, tagging each policy with the OS it came from.
- **Creating an auto-upgrade policy is `POST /upgrade-policy/policy`, singular** — the plural `POST /upgrade-policy/policies` **deactivates every policy in the scope**. A guard test pins the singular path so a future edit can't turn a migration into a mass deactivation of the customer's auto-upgrade.
- **Webhooks cannot be migrated by any API** — the entire `settings` resource is active-directory, microsoft, notifications, recipients, sms, smtp, sso and syslog; no tag in the 781-operation v2.1 spec exposes webhooks. `/notification-webhooks` was invented. The tool no longer pretends: backup reports `no API`, restore reports `manual`, and the migration-scope deck moves webhooks to the "re-create manually" slide instead of promising them.

### Changed
- Auto-upgrade policies are now captured at **group** scope as well as account and site — the API supports all four levels, and restricting the query to account/site would have silently dropped any group-level policy.
- New guard tests: the four dead paths cannot reappear as string literals, the required `/upgrade-policy/policies` query parameters must all be present, `create_auto_upgrade_policy` must use the singular path, and CI fails if `403` and `404` are ever handled identically again.

## v2.2.7 — 2026-09-01

### Bug Fixes
- **Config overrides were restored at the wrong scope, and more than once** — reported during the Beijer Ref migration (2026-08-31) as *"policy override did not make the transfer"*. `GET /config-override` returns the overrides of every **descendant** scope as well as the node's own — the mirror image of the inherited-rule trap that firewall, device control, STAR and tags each had to be taught about. Querying the account returned 14 group-scoped and 3 site-scoped overrides and not one that belonged to the account. Nothing filtered them, and the restore then overwrote each override's `scope` with the type of the node being restored, so all 17 would have been created at the account and then created again at every site and group beneath it — 47 create calls for 17 overrides. Each override is now restored only on the node that owns it, keeping its own scope.
- **Source-console IDs travelled with the override** — a config override echoes its `account`, `site` and `group` back as nested `{id, name}` objects. The field filter strips the flat `accountId` / `siteId` / `groupId` forms but never these, so the destination was being handed the source tenant's identifiers. They are removed before the create.
- **A selected element with nothing to restore vanished from the report** — the restore skipped it with no row, no log line and no error, which is indistinguishable from success. That is how the missing tags went unnoticed in 2.2.0, and it happened again: a backup that had never captured auto-upgrade policies, log-collection rules, webhooks or scheduled reports produced a clean report while the destination was missing all four, so it read as a failed migration rather than an incomplete backup. Every selected element now records a result, and the report distinguishes **`0`** (the backup held the data, nothing needed restoring) from **`0 (not in backup)`** (the backup never captured it). Applied to the blocklist, network-quarantine rules, STAR rules, saved filters, config overrides, log-collection rules, auto-upgrade policies, locations, webhooks and scheduled reports.
- **An override belonging to a scope outside the migration is now reported** — on the tenant above, one site-scoped override pointed at a site that wasn't part of the backup at all, so it had no destination node. Previously it was quietly misfiled at the parent scope; the run now states how many overrides were skipped and that they belong elsewhere, at both backup and restore time.

### Changed
- Backup stores only the overrides a scope actually owns, so the same override is no longer captured at every level above it. Backups taken before this release are corrected during restore — there is no need to re-capture.
- New guard test (`test_restore_coverage.py`) fails CI if an element that can be empty is restored without reporting a row, so the silent no-op cannot come back.

## v2.2.6 — 2026-08-23

### Bug Fixes
- **Every endpoint tag failed to restore, and the reported reason was the answer to a different question** — the beijerrefab migration (2026-08-21) failed all 173 unified endpoint tags at every scope with *"Validation Error :: data: type: Missing data for required field., key: Missing data for required field., value: Missing data for required field. (code 4000010)"*. Two faults, one on top of the other:
  - **The tag type was a guess, and it was wrong.** `POST /tag-manager` validates `type`, and every tag `GET /agents/tags` hands back is typed **`agents`** — the restore stamped `endpoints` on all of them, so the create was refused for every tag, on every scope, on every console. The tag's own type is now sent (defaulting to `agents`), never a guess.
  - **The error came from a request nobody meant to send.** After a rejection the client re-sent the tag inside a list, then inside `data.tags`, and reported whichever error came *last* — so the console's complaint about the real request was replaced by its complaint about a guess: all three fields were indeed "missing" from an envelope the schema was never going to read. There is one request now — `{"data": {…}, "filter": {…}}` — and the console's answer to it is what gets reported.
- **A key-only tag never sent its value** — `value` is required alongside `type` and `key`. The console stores `""` for a tag with no value, but the API rejects the field being absent, so tags like `ripple20` were refused even once the type was right. The empty string is now always sent.
- **Inherited endpoint tags were recreated under every child scope** — unified tags record their level in `scopeLevel`, not the `scope` field the named `/tags` objects use, so the filter that keeps a node to the tags it owns never applied to them: an account's tags were sent again for every site beneath it. They are now filtered like every other tag type, and a scope whose tags are all inherited logs the count it skipped instead of reporting a bare `0`.
- **A read-back the console can't answer no longer sinks a good create** — confirming a create that returned an empty body asks `GET /agents/tags?key__contains=…`; a console that rejects that filter made every such create "could not confirm". The scope is now re-read without the filter before giving up.
- **The diagnosis was probing a tag the console would always reject** — *Diagnose endpoint tags* built its throwaway tags with the same wrong type, so every request envelope failed for a reason that had nothing to do with the envelope. It now probes with the type the console reports.
- **STAR rule import always aimed at the tenant** ([#7](https://github.com/s1community/s1-command-center/issues/7), reported by ADDefender) — *"User 1449449408854677414:account can not create rule with higher scope None:tenant (code 4000010)"*. Both the Load and the Import on the STAR Rules page sent `{"tenant": "true"}` with no way to change it, so a token scoped to an account or a site was asking to create a rule above itself and every rule was refused. The page now has **Account** and **Site** boxes that scope both actions, exactly like Exclusions & Blocklist: blank means the tenant, a named Account means that account, and adding a Site narrows it further.
- **A scope-limited token no longer has to be told twice** — if a tenant create is refused for that reason and the token can reach exactly one account, the import moves to that account and reports where the rules landed. With several accounts reachable, only the operator can say which is meant, so the error is reported instead of guessing — and the dialog now says what to do about it.

### Changed
- **One scope resolver for the operations pages** — `resolve_scope_filter` / `scope_label` moved out of the Exclusions page to module level and both pages use them, so Account/Site behave identically wherever they appear.
- **The import loop is testable** — creating the rules moved into `pages_extra.import_star_rules(api, rules, scope, now)`, out of the Tk callback. It still prepares every rule with `migtools.prepare_star_rule` and still returns each failure with its reason.

### Tests
- 14 new: scope resolution (blank → tenant, account name → `accountIds`, site wins over account, case-insensitive matching, unknown names naming themselves), rules created at the scope asked for and prepared before sending, the reported failure recovering into the single reachable account, several reachable accounts reporting rather than guessing, a non-scope rejection not being retried elsewhere, and a guard that neither Load nor Import can go back to a hardcoded tenant.
- 12 more for endpoint tags, built on a tag object copied verbatim out of a real console backup rather than an assumed shape: the type is the console's own and is never guessed, `value` is always sent, a literal `"No Value"` survives, the read-only half of the object (ids, scope path, counters, timestamps) is not, `scopeLevel` filtering keeps a node to its own tags, a rejected create reports the console's reason and is not re-sent in another envelope, and the read-back falls back to a plain scope read. 269 tests total.

## v2.2.5 — 2026-08-21

### Bug Fixes
- **Exporting a report crashed on Windows** ([#3](https://github.com/s1community/s1-command-center/issues/3), reported by ADDefender) — `'charmap' codec can't encode characters in position 17809-17810`. Files were written with Python's default encoding, which is cp1252 on Windows, so one non-ASCII character anywhere in a report killed the export. The STAR Rules report hit it first because rule names and S1QL queries carry accents, dashes and quotes. Every file the app writes or reads is now explicitly UTF-8 — reports, backups, snapshots, restore and validation reports, migration manifests, the alerts CSV, saved connections, profiles, settings and the audit log. **Exports that didn't crash were also affected:** cp1252 bytes were being written into HTML that declares `charset="utf-8"`, so accented characters rendered as mojibake. Reading is fixed too, so a backup or rules file containing non-ASCII no longer fails to load on Windows.
- **Importing STAR rules created nothing and called it a success** ([#4](https://github.com/s1community/s1-command-center/issues/4), reported by ADDefender) — the STAR Rules page posted the exported JSON back unchanged, and `POST /cloud-detection/rules` refuses that three separate ways: read-only fields it doesn't accept (`id`, `creator`, `activeResponse`, the scope fields), null values that mean "use the default", and an `expiration` that has to fall inside the next six months — an exported rule's is usually in the past. Every rule was rejected, and the result was reported as `✓ Imported 0/1 STAR rules` at success level. The import now prepares each rule exactly as a migration restore does.
- **The reason was thrown away** — the import loop caught every exception and ignored it, so the console's explanation (which said precisely what was wrong) never reached the user. Each failure is now logged with the rule name and the API's own message, the summary is coloured and logged by outcome, and a failed import raises an error dialog naming the first few reasons instead of "Done".

### Changed
- **One implementation of the STAR create payload** — the restore path and the Operations import now share `migtools.prepare_star_rule`, along with `clean_for_restore` and the strip list, which moved into `migtools.py`. The Operations import had quietly missed every fix the restore path learned; sharing the code is what stops that recurring.

### Tests
- 15 covering the STAR payload: identifiers, scope fields, `activeResponse` and computed counters stripped; nulls dropped while `False`/`0` survive; expiry clamped when past or beyond six months, left alone when valid, and left for the console to reject when unparseable. Plus a guard that both call sites use the shared builder and the import doesn't return to swallowing errors.
- 4 for encoding, including a source guard over all 30 text `open()` calls in the app — the round-trip tests pass on macOS and Linux whatever the code does, since only Windows defaults to cp1252, so the guard is what actually protects the Windows build. 243 tests total.

## v2.2.4 — 2026-08-21

### Bug Fixes
- **The diagnosis blamed a permission it couldn't actually see** — when no request format produced a readable tag, the verdict named a missing `Tag Management.create` as the cause. A global-admin service user with Unified Tags granted 4/4 then produced exactly that verdict, so the claim was wrong: "the console discarded the write" and "the console stored it somewhere this tool doesn't read" are indistinguishable if you only ask one listing route and throw away the console's reply. Both possibilities are now reported, with what to check for each.
- **Endpoint tags were only ever looked for on one route** — the audit and the probe both read `GET /agents/tags` alone, so a console serving unified tags elsewhere would be reported as holding none. Every known route is tried, and the summary names the one that answered.
- **A tag whose key sits in a different field was invisible** — read-back matched `key` exactly and case-sensitively; `tagName` and `name` now count too.

### New
- **The console's own answer is kept and shown** — the probe records the response body for each request format and logs it. A response claiming a create, with nothing readable afterwards, is now its own verdict ("the write probably worked, the listing route is wrong") instead of being lumped in with a silent no-op — and it names the probe keys to search for, since tags that can't be found can't be cleaned up automatically.
- **Save the diagnosis as a report** — each format, its outcome, the route that read it back and the raw response. There's no way to copy the output console, and this is the artefact you actually need to send someone.

### Tests
- Seven more: the claimed-but-unreadable verdict, `affected: 0` still counting as a no-op, alternate-route discovery for both the audit and the probe, key matching on other fields, and the response bodies being retained. 224 tests total.

## v2.2.3 — 2026-08-19

### Bug Fixes
- **Result tables no longer print their first row on top of the column headers** — every operations page renders through the same table, and a batched load numbered its first row from the count taken *before* that row was added, so it landed on the header's grid row. Tk draws both, so the header and the first result sat on top of each other — visible on the Tags audit as "own" printed over "owned", and present on every page that loads results this way. Rows now start below the header where they belong.

### Tests
- Five tests pin table row placement: headers keep grid row 0, the first result starts at row 1, a reload doesn't shift anything, and no two widgets share a row across batch boundaries. They skip cleanly where there's no display. 217 tests total.

## v2.2.2 — 2026-08-16

### New
- **The tag audit is a page in the app, not a script** — v2.2.1 shipped the audit as `scripts/audit_tags.py`, which meant cloning the repo and running Python to answer "did my tags actually land?". That's not something a user of a packaged app should ever have to do, so the script is gone and the **Tags** page (Operations → Inventory) does the work:
  - **Run Audit** (read-only) walks the tenant and every matching account and site, listing what the console genuinely holds from both tag APIs — `GET /tags` for firewall / network-quarantine / device-inventory, `GET /agents/tags` for unified endpoint tags. Each scope's own tags are separated from the ones it inherits, so a restored site's tags aren't confused with its parent's. Filter by console, tag type, account and site; **Export Report** writes the whole audit to HTML/Excel/JSON.
  - **Diagnose endpoint tags** (writes, confirmation required) answers why a create silently fails: it sends each request envelope `POST /tag-manager` may accept, using a throwaway `s1cc-probe-…` key, re-reads to see which one the console really stored, and deletes them again. It reports the shape that works, or that the tag landed at the wrong scope, or that every shape was accepted and discarded — the signature of a token without `Tag Management.create`. Any tag it can't delete is named so it can be removed by hand.
- **An audit with no endpoint tags says what to do next** — finding zero endpoint tags in the audited scope is the exact symptom behind the v2.2.1 fix, so the summary calls it out and points at the diagnosis instead of leaving an empty table to interpret.

### Changed
- **Failed tag creates point at the page, not a script** — the restore's error detail now reads "open Tags (Operations → Inventory) and run 'Diagnose endpoint tags'".
- **The Tags page used to show firewall and network-quarantine tags only**, tenant-wide, with no notion of scope or inheritance. It now covers all four tag types across the scope tree.

### Tests
- 24 tests for the audit core (`tag_audit.py`) against a fake console: scope enumeration and filters, own-vs-inherited splitting including the fallback when the API ignores `scope=`, per-type error isolation, row flattening, and all four probe outcomes (stored / wrong scope / no-op / rejected) plus probe cleanup and undeletable leftovers. 212 tests total.

## v2.2.1 — 2026-08-16

### Bug Fixes
- **A tag create that the console discards is no longer reported as success** — the v2.2.0 restore of the beijerrefab tenant reported ~150 endpoint tags created with zero errors against a destination whose Tag Manager list stayed empty (reported by Joshua Tooley). `POST /tag-manager` answers `200` to a request body it doesn't store, and the restore trusted the status code. Endpoint tag creation now has to see a created object (an id, a non-empty list, or a positive `affected` count) in the response before it counts as new: a console that accepts and discards the request produces a visible error on the node instead of a phantom "N new".
- **Endpoint tag creation tries the shapes the route accepts — without ever duplicating a tag** — the scoped request is sent as `data` object, `data` array and `data.tags` array in turn, so a tenant that wants a different envelope migrates instead of silently doing nothing. A shape is only abandoned after the tag has been read back and confirmed absent (`GET /agents/tags?key__contains=…`): re-POSTing on an unconfirmed create is what would put three copies of every tag on a console that stores the tag but answers with an empty body. If the read-back itself fails, the create is reported as unconfirmed rather than retried. An `already exists` answer still surfaces immediately and is reported as "exists", never retried as a shape problem.
- **Failed endpoint tags are named in the report** — a key/value tag has no `name`, so the failure list identified it by its value alone ("Finance"). It now reads `key=value`.

### New
- **Tag audit tooling** — a read-only audit of every tag object a console holds, per scope, separating a scope's own tags from the ones it inherits, plus an opt-in write probe that finds which `POST /tag-manager` body the console really stores. Shipped here as a command-line script; moved into the **Tags** page in v2.2.2.

### Docs
- **Endpoint tags need their own token permission** — `Tag Management.view` / `Tag Management.create` are separate from `Tags.view` / `Tags.create` and are now listed in the API token permissions page. A token with only `Tags.create` restores firewall tags and leaves the endpoint tag list empty.

### Tests
- Regression coverage for the silent-success case: an empty `2xx`, `affected: 0`, shape fallback, the `409` passthrough, a create the console stored but didn't echo (must not re-POST), and a failed read-back (must not re-POST). 188 tests total.

## v2.2.0 — 2026-08-13

### Bug Fixes
- **Endpoint tags are finally restored** — selecting **tags_endpoint** backed the tags up, counted them in the preview and validation diffs and listed them as a restore element, but the restore loop had no branch for them at all. Nothing was created on the destination and no error was raised, so a targeted "restore tags" run reported success while the destination console stayed empty (reported by Joshua Tooley). Device-inventory (Ranger) tags now restore through `POST /tags`, and unified endpoint tags through the Tag Manager API.
- **Endpoint tag backup called a route that doesn't exist** — unified endpoint tags were read from `/endpoint-tags`, which is not a SentinelOne v2.1 endpoint. The resulting 404 was swallowed and shown as "n/a", so those tags never made it into the backup file. Listing now uses `GET /agents/tags` and creation `POST /tag-manager` (type `endpoints`, key/value pairs).
- **Tag creation no longer sends read-only fields** — firewall and network-quarantine tag payloads still carried `kind`, which the create endpoint rejects, and dropped the tag's scope. Payloads are now rebuilt from the writable fields only (`name`, `description`, `type`, `key`, `value`) with the destination scope stamped in, plus a retry without `scope` for consoles that don't accept it.
- **Inherited tags no longer duplicate down the tree** — `GET /tags` returns the tags a scope inherits from its parents, so restoring a site re-created the account and global tags at site level. Tags are filtered to the scope that owns them, matching the firewall / device-control / STAR behaviour. Tags with no `scope` field (older backups) are still restored.
- **A tag step that does nothing now says so** — each selected tag group always records a row in the restore report (`0` included) instead of vanishing from it, and the log explains when tags were skipped as inherited.

### Tests
- New `tests/test_restore_coverage.py` guard: every element in `BACKUP_ELEMENTS` must have a restore branch or a documented exception, so "captured by backup, silently skipped by restore" fails CI. Verified it flags `tags_endpoint` against the previous build.
- Added coverage for tag scope filtering, the `/tags` and Tag Manager payload builders, and the corrected endpoint-tag API routes. 180 tests total.

## v2.1.10 — 2026-07-29

### Bug Fixes
- **Saved filters now actually restore — and dynamic groups stay dynamic** — a migrated site could come out with none of its Deep Visibility filters, every dynamic group downgraded to **static**, and an empty **Group Ranking** page. All three were the same bug: `/filters` reports a filter's own scope as `scopeLevel`, and that source value was still being sent in the create payload even though the destination scope travels separately in the request's `filter` envelope. The console rejected every create, so no filters landed; group restore then couldn't resolve each dynamic group's filter by name and created it static, and S1 only ranks dynamic groups, so ranking came up empty. `scopeLevel` is now stripped alongside the other scope references. Re-running a restore repairs an affected site: the filters are created, each static group is upgraded back to dynamic, and the ranks are re-applied.

### New
- **Export STAR rules to Excel** — a **⭐ STAR → Excel** button on the Backup page reads every custom detection rule live from the selected console (no backup required) and writes a two-sheet workbook. *Summary* carries the console, filters, totals and breakdowns by scope / status / severity / account, plus a count of site rules that duplicate an account rule. *STAR Rules* lists all 24 customer-relevant fields per rule with a frozen header, auto-filter already switched on, and colour-coded scope, status and severity. Honours the page's Account Name / Site Name filters.
- **Targeted STAR rule cleanup** — `scripts/cleanup_duplicate_star_rules.py` gained `--site-name` / `--site-id` to limit a run to one site, and `--mode all-site-scoped` to remove *every* site-scoped rule at that site, whether or not a matching parent rule still exists — the cleanup for a site that a pre-2.1.9 build filled with copies of the tenant's global ruleset. It refuses to run without a site target, warns before deleting, and `--out` writes an audit list (in dry-run too).

### Tests
- Added coverage for saved-filter payload cleaning, STAR scope filtering in the global→site direction, the new cleanup modes, and the Excel export (value formatting, sorting, workbook structure). 160 tests total.

## v2.1.9 — 2026-07-28

### Bug Fixes
- **Custom detection (STAR) rules no longer duplicate across scopes** — an account-scoped rule was captured at the account *and* under every child site, then re-created at each one, so a single rule ended up repeated per site on the destination console. `/cloud-detection/rules` returns inherited rules at every scope level; backup and restore now filter each rule to its own scope, matching the existing firewall / device-control behaviour. The restore-side filter also repairs backups taken with earlier builds, so no re-capture is needed.

### New
- **Duplicate STAR rule cleanup script** — `scripts/cleanup_duplicate_star_rules.py` finds site-scoped rules that duplicate an account/global rule (matched on account + name + description + query) and bulk-deletes them through the Delete Rules API, since the console UI can't filter or bulk-select by site scope. Dry-run by default; `--delete` to apply, `--yes` to skip the prompt.

### Tests
- Added regression coverage for STAR scope filtering: a site node drops the inherited account rule, an account node drops descendant site rules, and the tenant level accepts both `global` and `tenant`. 138 tests total.

## v2.1.8 — 2026-07-28

### Bug Fixes
- **Backup name filters now prefer an exact match** — typing a specific **Site Name** like `Servers` no longer also backs up supersets such as `HighQ_Servers` or `TR-Servers`. When a name matches exactly it wins; if nothing matches exactly, partial (substring) matching still works as a fallback. The same exact-preferred rule applies to the **Account Name** and **Group Name** filters and the migration/preview tree.

### Tests
- Added regression coverage for exact-preferred site filtering (exact vs. substring fallback vs. blank) and the `_select_by_name` helper (case / whitespace / zero-width normalization).

## v2.1.7 — 2026-07-27

### Bug Fixes
- **Custom RBAC roles now restore correctly** — role creation was rejected by the console with "Unknown field" / "Missing required field" validation errors. Restore now sends the role scope as the required top-level `filter`, drops the read-only fields the API rejects (`scope`, `predefinedRole`, `accountIds`, `pages`), and rebuilds each role from the destination console's own role template so permissions carry over even across consoles with different licensed features.
- **Backup account matching is more reliable** — Account Name filters now normalize invisible Unicode/control characters, copied rich-text spacing, and case before matching API account names. If a stale ticket account ID is present, backup falls back to the visible Account Name instead of returning 0 nodes.

### Tests
- Added regression coverage for the role create envelope (`filter` + cleaned `data`), the role-template endpoint, and the permission overlay onto the destination template.
- Added regression coverage for account filters containing invisible characters and stale account-ID fallback.

## v2.1.6 — 2026-07-22

### Bug Fixes
- **API calls no longer fail with opaque decompression errors** — requests now prefer uncompressed JSON responses, and any bad compressed response is wrapped with the API endpoint and a clear decode-failure message.

### Tests
- Added regression coverage for uncompressed API request headers and compressed-response decode failures. 123 tests total.

## v2.1.5 — 2026-07-22

### Improvements
- **Account-scoped RBAC roles are now backed up and restored** — role backup now queries the selected account scope and captures full role definitions; restore re-creates custom account roles before creating console users so role assignments can map by name.
- **Restore element info icons work again** — the ⓘ buttons now open hover/click tooltips instead of silently writing help text to the output console.
- **Restore log export defaults to JSON** — JSON is now the default export format, and the HTML report expands the full operation log by default when selected.
- **Source vs destination validation now compares every item** — large exclusion sets are no longer sampled at 50 entries, so missing path exclusions deep in a 300-item list are surfaced in the validation export.
- **Operations → Exclusions & Blocklist is scope-aware** — add Account/Site filters to load account/site-scoped exclusions instead of only tenant-scoped entries.

### Tests
- Added regression coverage for scoped RBAC role APIs, role restore payload cleanup, and validation of exclusion lists beyond 50 items. 121 tests total.

## v2.1.4 — 2026-07-14

### Improvements
- **Restore progress bar redesigned** — The progress bar, elapsed timer, and live status used to be packed to the right of the RUN buttons, so on a wide window they floated far from the controls with a large empty gap in the middle. They now sit in a dedicated **full-width strip directly under the RUN buttons**: the bar spans the whole page (taller, rounded, green fill) with the timer and status aligned to its right.

## v2.1.3 — 2026-07-14

### Improvements
- **macOS Keychain toggle now warns before it bites** — Enabling **Settings → Security & Storage → "Store API tokens in OS keychain"** on an *unsigned* build makes macOS prompt for keychain permission on **every launch** and again after **every update** (the "Always Allow" grant is tied to the app's code signature, which changes each build). The toggle now shows a confirmation explaining this before it turns on, and reverts if you decline. Default remains **OFF** — tokens live in an owner-only (`0600`) file with no prompts. **If you're getting the keychain prompt after upgrading, turn this toggle OFF** and your tokens migrate back to the file.

## v2.1.2 — 2026-07-14

### Bug Fixes
- **Restore no longer looks like it's stuck "Snapshotting" while it's actually restoring** — After the pre-restore snapshot finished, the status label kept showing the last `📸 Snapshot …` text for the entire restore (the restore loop updated the node table but never the status label), so a running restore looked like it was still snapshotting. The snapshot label is now clearly prefixed `📸 Snapshot`, cleared the instant the snapshot completes, and the restore drives a live `Restoring i/total: <node>…` label — the current phase is always unambiguous.

## v2.1.1 — 2026-07-14

Restore reliability release.

### Bug Fixes
- **Policy restore no longer fails on forensics auto-triggering** — Restoring a policy whose `forensicsAutoTriggering` points at a RemoteOps forensic-script profile that doesn't exist on the destination failed the *entire* policy with *"Bad auto-triggering policy information provided (code 4000010)"* (hit on every group policy). Restore now detects this, drops just the forensics-auto-trigger block, and retries so the rest of the policy still lands — re-point it manually once the profile exists on the destination. Verified live against a destination console (error reproduced, then fixed).
- **STAR custom-detection rules no longer rejected on restore** — Creating a STAR rule failed with *"data: activeResponse: Unknown field (code 4000010)"*. `activeResponse` is a read-only flag the API returns on read but rejects on create; it is now stripped before the rule is created. Verified live.

### Improvements
- **"Snapshot first" is now interruptible and shows progress** — The pre-restore destination snapshot could look frozen: it is a full backup of the destination scope with no progress feedback, and Skip/Stop had no effect during it. It now reports per-node progress (`i/total: path`) and honors **Skip**/**Stop** mid-snapshot (whatever was captured so far is still saved for rollback).
- **Per-element Skip button** — The Skip button now names the element/phase currently running (e.g. *"⏭ Skip FW rules"*), and every restore step — bulk items, custom loops, the snapshot phase, and single-shot settings — honors it and re-enables between elements, so each element is independently skippable without a Skip click leaking into the next element.

### Tests
- Regression coverage for the policy forensics-drop retry and the STAR `activeResponse` strip. 109 tests total.

## v2.1.0 — 2026-07-13

UI/UX release.

### New
- **Settings page** — a **⚙ Settings** button in the sidebar footer opens a preferences page: theme (Light / Dark / System), UI scale, start-in-fullscreen, open OUTPUT console on launch, default "Snapshot first" for restores, OS-keychain token storage, and default "Ignore SSL errors" for new connections. Preferences auto-save (plus a **Save Settings** button) to `~/.s1-command-center/settings.json` and persist across restarts **and app updates** (unknown/future keys are preserved so nothing is lost across versions).
- **Light / Dark mode** — a full light theme with a live Light / Dark / System switch (CustomTkinter widgets flip instantly; the diff/progress/tooltip tk panels follow via a small colour-token system).

### Improvements
- **Restore page re-organized by workflow** — the action bar is grouped into three labeled phases: **1 · Prepare** (Pre-flight, Preview vs Dest, Set Defaults, Snapshot first), **2 · Run** (Restore, Auto Restore, Resume, Stop, Skip Element), and **3 · Review** (Export Log, Explain Errors, Redacted Copy, Rollback).
- **Restore account-name guard** — before restoring, if none of the backup's account names exist on the destination console, the app warns and offers to jump to Structure Operations → Mangle Rename, so a mismatched name doesn't silently create a new account.
- **Picture logo in the sidebar** — the header shows the app's radar logo image instead of the text "S1" tile (falls back to the tile if unavailable).
- **Fullscreen** — ⌘⇧F (or F11) toggles fullscreen, Esc exits.
- **Help tooltips** — the "?" buttons show a hover/click tooltip instead of writing help into the OUTPUT console.

### Bug Fixes
- **App no longer closes itself on macOS** — a help tooltip used a `-topmost` borderless `Toplevel` that could tear down the whole app a few seconds after launch. Removed `-topmost`; added a heartbeat check to catch this class of regression.

## v2.0.3 — 2026-07-13

### Bug Fixes
- **App no longer crashes on startup** — v2.0.1 and v2.0.2 crashed immediately on launch with `NameError: name 'APP_VERSION' is not defined`: the sidebar footer referenced the app version without `app.py` importing it from `config`. Fixed the import and added a regression test so it can't recur.

## v2.0.2 — 2026-07-13

### Improvements
- **No more macOS keychain prompts** — OS-keychain token storage is now opt-in (`S1CC_ENABLE_KEYRING=1`) instead of on by default, so macOS no longer shows the "S1 Command Center wants to use your confidential information stored in 's1-command-center'" login-keychain prompt on every token read/write. Tokens are kept in the owner-only (`0600`) `contexts.json` unless you opt back in; it still degrades to file storage on any keychain failure.

## v2.0.1 — 2026-07-13

### Improvements
- **Reset All is a true clean slate** — 🔄 Reset All now permanently deletes every saved connection (source & destination, plus their OS-keyring tokens) in addition to clearing all page fields, so nothing carries over into the next migration.
- **Jira-ready completion report** — The Migration Complete popup's "📋 Copy All" text now leads with a `cc: @migration-team` mention placeholder and a `Migration was completed with S1 Command Center vX.Y.Z for the <scope>` summary line, ready to paste straight into the ticket.

## v2.0.0 — 2026-07-08

Major version milestone. Rolls up the v1.8.x migration-workflow and verification work into a stable **2.0** release, plus the firewall-rule migration fixes below.

### Bug Fixes
- **Firewall rules with multiple IPs now transfer completely** — Multi-IP firewall rules were being restored with only a single IP (the first host, whether IP, CIDR or FQDN; multiple *ports* were unaffected). S1 v2.1 stores multiple hosts in the plural `remoteHosts`/`localHosts` arrays (each entry `{type, values:[...]}`), but the restore field-whitelist only kept the legacy singular `remoteHost`/`localHost` (which carries just the first host), so every extra IP was silently dropped. The whitelist now keeps the plural arrays, and the singular field is dropped when the plural form is present so it can't clobber the rule back down to one IP. Existing backups already contain the full data — just re-run the restore.
- **Inherited firewall rules no longer leak into child-scope restores** — The firewall-control API returns inherited rules at every level, so a site/group node's backup includes the account/global rules that flow down to it. Restore re-created those parent-scope rules at the child scope — e.g. unchecking the **Account** restore level still created the account's firewall rules at the site. Firewall rules are now filtered to the node's own `scope` before restore (matching the existing Device Control behaviour); the shared `_rules_for_scope` helper backs both.

## v1.8.0 — 2026-06-30

### Migration workflow
- **Migration Runbook** — A new guided page (top of the MIGRATION section) that sequences the whole job as an ordered checklist: connect → pre-flight → backup → preview → restore → validate → manifest. Each step opens the relevant page; some auto-detect completion (connected, backup taken, validated), the rest are operator-confirmed, with a progress bar.
- **Pre-flight readiness check** — ✈ Pre-flight button on the Restore page validates *before* you commit: destination reachable, token valid/not-expiring and scoped wide enough for the target, and whether the target scope already exists. Read-only; returns pass/warn/fail with reasons.
- **Agent-migration reconciliation** — After an agent move, ✓ Verify Move reconciles counts (source dropped, destination gained the expected number) and lists stragglers — the agent workflow finally has verification instead of fire-and-hope.

### Verification
- **Field-level settings/policy diff** — Validation no longer stops at "present on both" for the singletons. Policy, the three module configs, and SSO/SMTP/syslog/AD now get a value-level field diff (volatile keys like ids/timestamps/scope ignored), so "present" becomes "present *and identical*, or here's the field that differs".

### Operations
- **Operation audit history** — Every backup/restore/validate/agent-migrate is appended to `~/.s1-command-center/audit.jsonl` (owner-only). A 📜 History button shows recent operations.
- **Scheduled backups** — ⏰ interval selector on the Backup page (Hourly/6h/12h/Daily) runs the current backup automatically while the app is open, saving timestamped files to `~/.s1-command-center/scheduled-backups/`. (True app-closed scheduling still needs an OS scheduler.)

### Tests
- New `migtools.py` (pure logic: audit log, pre-flight evaluation, agent reconciliation, field diff) with `test_migtools.py` — 15 cases. 81 tests total.

## v1.7.0 — 2026-06-29

### Reliability / scale
- **Rate-limit visibility** — The API client now tracks HTTP 429 throttling (`throttle_stats()` + an `on_throttle` hook). A backup/restore that slows down because the tenant is rate-limiting now says so in the log ("⏳ console is rate-limiting us… backing off") instead of looking frozen. (Parallelising node reads for raw throughput is the next step and is intentionally deferred until it can be tested against a live tenant.)

### Build
- **Keyring bundled** — `S1 Command Center.spec`, `build_macos.sh`, and `build_windows.bat` now collect `keyring` + the platform backend (macOS Keychain / Windows Credential Manager / Secret Service), so OS-keyring token storage works in the packaged app. Guarded so builds still succeed if keyring is absent.

### Security
- **API tokens can live in the OS keyring** — When the `keyring` package and a working OS backend (macOS Keychain / Windows Credential Manager / Secret Service) are present, tokens are stored there and `contexts.json` holds only a sentinel instead of the plaintext token. Degrades gracefully to the previous file storage if keyring is missing or fails (no lockout — a missing token just prompts re-auth); `S1CC_DISABLE_KEYRING=1` forces file storage.
- **Redacted backup export** — Backups embed real secrets (SMTP/AD/SSO/syslog passwords, tokens, keys). The Restore page now flags a loaded backup that contains secrets and offers **🛡 Redacted Copy** — a sanitised JSON safe to attach to a ticket or share, with every secret value masked. The working backup used for restore is never modified.

### Migration
- **Dry-run preview before restore** — New **🔍 Preview vs Dest** button on the Restore page compares the loaded backup against the *live* destination **without writing anything**, and reports per-element how many items would be newly created vs already exist (and which scopes are missing entirely and would be created). Reads through the shared full reader, and also fills the Source-vs-Destination panel so you can review before committing. Completes the safe-change loop: preview → snapshot → restore → validate.
- **Validation now covers every migrated element** — Migration Validation previously compared only ~12 of the backed-up element types (policy, exclusions, blocklist, firewall/DC/NQ *rules*, saved filters, config overrides, console users), so it could report "identical" while STAR rules, threat-intel IOCs, tags, roles, service users, gateways, webhooks, scheduled reports, log-collection/auto-upgrade rules, the three module *configs*, and all five settings blocks were never checked. Validation now reads both consoles through the **same** `_read_node` backup reader (no second element list to drift) and compares all of them — collections by item name, configs/settings by presence. A guard test (`test_validation_coverage.py`) fails CI if a future backup element has no validation category.
- **Pre-restore snapshot + rollback** — With **📸 Snapshot first** ticked (default), a restore first backs up the destination's *current* state of the same scope/elements to `~/.s1-command-center/snapshots/`, reusing the exact backup reader so the file is restore-compatible. The new **↩ Rollback** button loads the latest snapshot back into the loader to revert a bad restore. Skipped automatically on Resume; snapshot failure is logged loudly but does not abort the restore.
- **Migration profiles** — Save the current scope (levels + name filters) and element selection as a reusable named profile (**Profile ▸ Save/Load/Delete** on the Backup page). Profiles are stored in `~/.s1-command-center/migration_profiles.json` and hold **no credentials**. Repeat/multi-site migrations become one click.
- **Migration manifest + PSO comment** — After a validation, **🧾 Migration Manifest** exports a structured JSON manifest of what moved and how it verified, plus a ready-to-post PSO ticket comment (Markdown, copied to the clipboard) that feeds the *"done with PSO-XXX"* ticket-closing workflow.
- **Remote Scripts element** — The Remote Scripts library is now captured by backup and listed on restore for manual re-upload (inventory-only — the script body lives in per-tenant cloud storage and isn't returned by the API). Brings the element count to **33**.

### Docs
- **Supported-Elements** rewritten to match the code (33 elements), marking inventory-only elements and documenting why **Custom Dashboards** and **Ranger/Network-Discovery** data are not migratable (no settable API surface).

### Tests
- New pure-logic suites for the migration manifest builders and the profile manager (`test_manifest.py`, `test_profiles.py`).
- **Validation coverage guard** (`test_validation_coverage.py`) pins the comparison engine to `BACKUP_ELEMENTS`.
- **Static wiring check** (`test_wiring.py`) asserts every `command=self._x` widget callback resolves to a real method — catches launch-crash bugs without a display.
- **Dry-run resolver** (`test_preview.py`), **redaction** (`test_redaction.py`), and **keyring fallback** (`test_config_keyring.py`) suites. 62 tests total.

## v1.6.0 — 2026-06-29

### UI Redesign
- **New design system** — Complete visual overhaul around the SentinelOne brand violet (`#7C3AED`) on a refined slate-charcoal dark theme, centralised in `theme.py`. All default widgets adopt the palette automatically; ~230 hardcoded inner-page colours were swept onto the new tokens.
- **Cross-platform fonts** — Native system fonts per OS (SF Pro Text/Menlo on macOS, Segoe UI/Consolas on Windows) instead of Windows-only families that fell back to an unstyled default elsewhere.
- **Redesigned sidebar** — Violet brand lockup, connection-status card with live SRC/DST dots, section eyebrows, active-indicator bar, and a distinct violet panel around the MIGRATION workflow.
- **OUTPUT drawer** — The log moved from a cramped bottom strip to a collapsible, resizable drawer driven by an always-visible status line that mirrors the latest (colour-coded) log entry. Help (**?**) buttons open it automatically.
- **Adaptive scaling** — Window opens proportional to the screen and the UI auto-scales with window size; manual zoom via ⌘/Ctrl +/-/0.

### Safety
- **Critical-operation lock** — During a backup/restore, all controls except Stop / Skip Element (and the log drawer) are disabled to protect the running job.

### Security & Quality
- **Hardened credential files** — `contexts.json`, Atlas token, and backup JSON written `0600`; config dir `0700`.
- **Reproducible builds** — `requirements-lock.txt` added; fixed an unsatisfiable `requests` floor.
- **Tests** — New pytest suite (API retry/error handling + restore helpers) and `requirements-dev.txt`.
- **Backup error visibility** — Silent `except: pass` blocks in the backup path now log warnings.
- **Restore refactor** — Pure helpers hoisted to module level (unit-tested) and duplicate summary logging consolidated.

## v1.5.3 — 2026-06-23

### Bug Fixes
- **Unified exclusions restore fix** — Fixed 93/93 failures caused by missing required fields on POST `/unified-exclusions`. The API requires `scopeLevel` and `scopeLevelId` in the filter (not data), `exclusionName` (mapped from `name` if absent), `reason` (defaults to `"other"`), and `recommendation` (defaults to `"NONE"`). The GET response uses different field names than POST expects.

## v1.5.2 — 2026-06-23

### Build
- **Custom PyInstaller bootloader** — The Windows build now compiles PyInstaller's bootloader from source instead of using the pre-built binary. The pre-built bootloader hash is shared by thousands of apps (including malware) and is a known false-positive trigger for heuristic AV/EDR engines (`windows.preExecutionSuspicious`). A unique bootloader binary eliminates this trigger.
- **Windows code-signing scaffolding** — Added conditional signing steps (mirrors the macOS pattern). When `WINDOWS_SIGN_CERT_P12` and `WINDOWS_SIGN_CERT_PASSWORD` secrets are populated, the build signs all `.exe`, `.dll`, and `.pyd` files in the bundle plus the Inno Setup installer using SHA-256 + RFC 3161 timestamp.

## v1.5.1 — 2026-06-23

### New Features
- **Unified Exclusions support** — Backup and restore now support SentinelOne's Unified Exclusions API (`/unified-exclusions`), including **tag-based exclusions**. Select `unified_exclusions` in the backup element list to capture all modern exclusion types that the legacy `/exclusions` endpoint misses.
- **Load Unified button** — The Exclusions & Blocklist page now has a purple **Load Unified** button to browse all unified exclusions (including tag-based) from the source console.

### Bug Fixes
- **255-character name truncation** — Exclusion names longer than 255 characters (allowed by the SentinelOne UI but rejected by the API) are now automatically truncated on restore, preventing bulk failures.
- **Non-printable character scrubbing** — Extended to unified exclusion fields (`exclusionName`, `note`) in addition to the existing `value` and `description` scrubbing.

### Error Handling
- New error classifiers for unified exclusion validation failures and the 255-char name limit, with actionable fix guidance in the Explain Errors panel.

## v1.5.0 — 2026-06-22

### New Features
- **⚡ Auto Restore** — New button that runs a fully automatic migration with zero prompts. Automatically creates all missing accounts, sites, and groups on the destination. No confirmation dialogs, no filters — click and walk away.
- **↻ Resume** — New button to resume a previously stopped or failed restore from exactly where it left off. Already-completed nodes are skipped; cancelled and errored nodes are retried automatically.
- **Auto-create accounts** — When an account doesn't exist on the destination, a custom dialog offers three choices: **Create** (this account), **Create All** (all remaining missing accounts), or **Skip** (skip this account and its children). Replaces the old system Yes/No/Cancel dialog with clear labels.
- **Auto-create sites & groups** — Sites and groups under auto-created accounts are created automatically during migration. Parent site "not found" errors for child groups are resolved.
- **Filter bypass for global restores** — When the Global checkbox is checked (or Auto Restore / Create All is used), account/site/group name filters are automatically bypassed. Prevents accidental filtering from leftover ticket-paste values.

### UI
- **Reorganized button layout** — Buttons are now arranged in two clear rows with color-coded groups:
  - **Row 1**: Launch (green — Restore, Auto Restore, Resume), Control (red/orange — Stop, Skip Element), Progress bar + timer (right-aligned)
  - **Row 2**: Results (blue — Export Log, Explain Errors), Setup (gray — Set Defaults)

### Improvements
- **Smarter license handling** — Account creation now uses only the primary bundle from the destination, stripping add-on bundles (Purple AI, Ranger, etc.) that cause "not available in your scope" errors. Retries with progressively simpler bundle configurations if the first attempt fails.
- **Auto-mode for site conflicts** — In Auto Restore mode, default-site conflicts are auto-resolved (Scenario A: overwrite placeholder) and missing sites are auto-created without prompts.
- **SKU fix auto-accept** — In Auto Restore mode, SKU/bundle mismatch fixes are applied automatically.

## v1.4.0 — 2026-06-03

### New Features
- **Migration Validation page** — New MIGRATION tab that compares the **live source** console against the **live destination** and explains every difference in plain English.
  - Matches accounts/sites/groups by name (rename-aware: when one account/site exists per side, source names are remapped to destination names so renamed scopes still pair up).
  - Diffs every config element (policy, exclusions, blocklist, firewall rules/locations, device control, network quarantine, saved filters, config overrides) by count **and** by item name, using a multiset comparison so duplicate names (e.g. firewall rules) surface the exact extra/missing items.
  - GUI shows a compact per-node summary listing the exact missing (red) and extra (yellow) item names. The HTML **Export Report** elaborates: every differing item is listed by name with a per-row "why" and "what to do".
  - Source/Destination URLs and scope entries are shown inline and auto-filled by **Paste from Clipboard** (ticket).

### Dependencies
- Bumped `requests` (>= 2.34.2) and `Pillow` (>= 12.2.0). `customtkinter` (>= 5.2.2) and `openpyxl` (>= 3.1.5) unchanged (already latest).

## v1.3.8 — 2026-05-29

### Analytics
- **Public usage dashboard** at `docs/index.html` (live at `https://s1community.github.io/s1-command-center/` once GitHub Pages is enabled on the repo). Single static page that reads the public GitHub Releases API and renders:
  - Total-downloads stat card, macOS vs Windows split, latest-version adoption %.
  - Per-version stacked bar chart (macOS / Windows series).
  - Platform-split doughnut chart.
  - Full per-release table with per-asset download counts and size, including a horizontal bar for relative-share-within-release.
  - Auto-refreshes every 5 minutes; manual refresh button.
- Chosen approach: **zero client-side telemetry**. The app itself sends nothing — no event collection, no opt-in dialog, no third-party processor. The dashboard reads only what GitHub already publishes publicly (download counts on release assets), so there is no AppSec / privacy / EDR-false-positive exposure. This is the safest first step toward usage insight; a fuller Tier-2 telemetry path (Cloudflare Worker + anonymous device events) was scoped and rejected in favor of this for now.

## v1.3.7 — 2026-05-29

### Documentation (macOS)
- **DMG `README.txt` leads with the one-liner installer.** v1.3.6 introduced the one-line Terminal installer but only mentioned it in the repo `README.md`, so users who downloaded the DMG had no idea it existed and were still doing the drag-to-Applications + Gatekeeper-bypass dance. The DMG README now leads with "FASTEST INSTALL" featuring the curl-pipe-bash command, framed as the recommended path. The drag-to-Applications flow is preserved underneath as a fallback.
- **GitHub release notes** now lead with the one-liner installer at the very top of every release page, instead of "`.dmg` — Double-click to install" (which led users straight into the Gatekeeper trap).

## v1.3.6 — 2026-05-29

### Packaging (macOS)
- **One-line installer** — New recommended install path for macOS:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/s1community/s1-command-center/main/installer/install.sh)"
  ```
  Resolves the latest GitHub release, downloads the DMG, mounts it, copies the app to `/Applications`, strips the `com.apple.quarantine` xattr, and launches it. **Zero Gatekeeper prompts** — because Gatekeeper only enforces on Finder double-clicks (LaunchServices), not on Terminal-invoked binaries, and we strip the quarantine flag before any `open` call. Supports `S1CC_VERSION=vX.Y.Z` to pin a version and `S1CC_NO_LAUNCH=1` to skip the final auto-launch. Manual DMG install is still supported for users who prefer GUI.
- **README install section restructured** — Featured one-line install at the top, manual DMG install below, with cross-links between the install path and the Troubleshooting section. The troubleshooting `xattr -cr` command is now called out explicitly as the fastest GUI-install fix.

## v1.3.5 — 2026-05-29

### Packaging (macOS)
- **Dropped the `Install & Launch.command` script** — In macOS Sequoia (15.x) Apple removed the right-click → Open Gatekeeper bypass for unsigned shell scripts, so the very script that was meant to *work around* Gatekeeper was itself being blocked by Gatekeeper ("Apple could not verify Install & Launch.command"). The DMG now uses the canonical drag-to-Applications layout: `S1 Command Center.app` sits next to an `Applications` symlink. Users drag the app across, then unblock on first launch via *System Settings → Privacy & Security → Open Anyway* (one time, then macOS remembers). Removes one Gatekeeper prompt from the install flow entirely.
- **DMG `README.txt` rewritten** with explicit Sequoia / Sonoma / Ventura bypass steps and a Terminal `xattr -cr` fallback for stubborn cases.

## v1.3.4 — 2026-05-29

### UI
- **New app icon** — Replaced the legacy icon with a command-center radar scope in SentinelOne brand purple. Built from scratch (`scripts/build_icon.py`) at native resolutions for every platform target: Windows `.ico` ships 16/32/48/64/128/256, macOS `.icns` ships 16…512@2x (1024px). macOS build now consumes the native `.icns` directly instead of letting PyInstaller convert the Windows `.ico`.

## v1.3.3 — 2026-05-28

### Packaging
- **Windows full installer** — Releases now ship `S1-Command-Center-Windows-Setup.exe` alongside the portable ZIP. The installer (built with Inno Setup 6) installs to `Program Files\S1 Command Center`, creates Start Menu and optional desktop shortcuts, and registers a proper uninstaller in *Add or Remove Programs*. The portable ZIP remains available for users who can't run installers.

## v1.3.2 — 2026-05-28

### Bug Fixes
- **Windows EDR false-positive on export** — Auto-opening exported reports via `os.startfile()` (Windows) and `subprocess.Popen(["open"|"xdg-open", ...])` (macOS/Linux) tripped behavioral-detection thresholds in some endpoint agents (including S1), causing the app to be quarantined immediately after launching an export. Export now writes the file and logs the full path to the OUTPUT console instead of spawning a child process to open it. Users can open exported files manually from the logged path.

### Dependencies
- `customtkinter` >= 5.2.2
- `requests` >= 2.32.3
- `openpyxl` >= 3.1.5
- `Pillow` >= 11.0.0

## v1.3.1 — 2026-05-23

### Bug Fixes
- **Exclusion paths with invisible Unicode characters** — Source consoles sometimes accumulate U+200E (LTR mark), zero-width joiners, BOMs, etc. in copy-pasted paths. The destination's stricter validator rejects every such exclusion with `Invalid value <x> contains non-printable characters`. Restore now scrubs these characters from `value` and `description` fields on exclusions before submitting.
- **Notification recipients payload shape** — `PUT /settings/recipients` was wrapped as `{"data": {"emails": [...]}}`, which S1 rejects with `data: dict_values(['emails']): Unknown field`. Now sends the list directly as `{"data": [...]}` with two fallback shapes (`{"recipients": [...]}` and per-recipient POST) so the tenant variant is auto-detected.
- **Firewall rules with cross-console location bindings** — Source `locationIds` never match destination location IDs, so every location-aware firewall rule failed with `Invalid locations for this scope`. Restore now detects this error, retries once with location fields stripped, and the rule lands as a location-agnostic rule. A log warning reminds the operator to re-attach Locations in the destination console.

### Better Error Explanations
- **"Cannot change firewall settings while inheriting from parent"** — Now correctly classified under the "Scope inherits from parent" rule with explicit instructions to decouple Firewall Control / Device Control / Network Quarantine at the affected scope.
- **"Invalid locations for this scope" (fw-rule)** — Dedicated explanation describing why source location IDs never match the destination.
- **"data: dict_values(['emails']): Unknown field" (recipients)** — Dedicated explanation pointing to v1.3.1+ where the payload shape is fixed.
- **"non-printable characters" (exclusions)** — Folded into the existing path-validation rule.

## v1.3.0 — 2026-05-22

### New Features
- **Live DiffPanel on Restore page** — side-by-side comparison of every backup node vs the live destination console. Shows identity (type, filterId/filterName, inherits, etc.) and per-element counts + sample names. Snapshots the destination automatically before and after each node is processed during a restore so the operator can see exactly what changed.
- **Pinned-group preservation** — groups with `type=pinned` on the source are now created as Pinned on the destination (`POST /groups` with `type=pinned`). Existing groups are converted via a multi-endpoint fallback chain (`/move-to-pinned`, `/move-to-pin`, `/pin`, or PUT) with verification that the type actually flipped.
- **Dynamic-group restoration by filter name** — backup now back-fills `filterName` on every dynamic group from the source console (so the saved-filter reference travels with the backup). Restore resolves the source filter name to the destination's matching saved-filter ID and binds the group accordingly. A per-restore cache prevents repeated `/filters` lookups per site.
- **Resizable progress UI** — Restore page progress table and DiffPanel sit in a draggable `PanedWindow`. Rows are numbered, paths are shortened with a hover-tooltip showing the full path, Details column wraps to multiple lines, and the table auto-scrolls to the row currently being processed. Mouse-wheel events now propagate from any child widget.

### Bug Fixes
- **Dynamic groups silently restored as static** — `_resolve_dest_id` now overwrites an existing destination group's `filterId` when the source is dynamic and the destination is static. Earlier versions only matched by name and returned the existing ID without comparing settings.
- **`PUT /groups/{id}` rejects `type` field** — restore no longer sends `type` on the update (S1 infers it from filterId presence). Fixes `4000010 Validation Error :: data: type: Unknown field`.
- **Group create with `inherits=false`** — now always creates with `inherits=true`; the per-node policy step decouples and pushes the source policy a moment later. Fixes `4000010 Policy should be delivered if it is not inherited`.
- **Config overrides rejected for missing scope** — re-injects `data.scope` (`"account"|"site"|"group"|"global"`) after `_clean_for_restore` strips it. Fixes `data: scope: Missing data for required field`.
- **Unrecognised exclusion errors** — S1 API error extractor now reads `title + detail + code` from every error object (previously only `detail`, which was often blank). Per-item failure records keep the full message (was truncated to 80 chars), so the error-classifier actually has text to match on.
- **DV / saved-filter drift across consoles** — restore matches by name against the destination's filters per site and substitutes the destination ID; never sends stale source IDs.

### API Methods Added
- `update_group(group_id, data)` — `PUT /groups/{id}` for in-place overwrite (name/filterId/description/rank/inherits).
- `move_group_to_pinned(group_id)` — multi-endpoint convert chain with graceful fallback.

## v1.2.0 — 2026-05-08

### New Features
- **Purple AI Page** — Natural language queries against SDL telemetry via GraphQL. Supports EDR, IDENTITY, CLOUD, NGFW, DATA_LAKE view selectors with configurable time windows and clickable suggested follow-up questions.
- **Unified Alerts Page** — Modern multi-source alert triage via UAM GraphQL API. Filter by status/severity/view, paginated listing, faceted counts, alert detail/notes/history/timeline, bulk triage (Resolve/In Progress), and CSV export.
- **Connection Pooling** — `HTTPAdapter` with pool of 32 connections for better socket reuse during backup/restore operations.
- **429/5xx Retry** — All HTTP methods (GET, POST, PUT, DELETE) now retry on rate limit (429) and server errors (5xx), honoring the `Retry-After` header.
- **Parallel Fan-out** — New `get_many()` method for concurrent independent GETs via ThreadPoolExecutor.
- **GraphQL Transport** — Shared `_gql()` method for Purple AI and Unified Alert Management.

### API Methods Added
- `purple_query()` — Purple AI natural language → Power Query
- `uam_list_alerts()` — Paginated alert listing with filters
- `uam_get_alert()` — Single alert detail with assets
- `uam_facets()` — Severity/status/product faceted counts
- `uam_alert_notes()` / `uam_add_note()` — Read/write alert notes
- `uam_alert_history()` / `uam_alert_timeline()` — Audit trail
- `uam_set_status()` / `uam_set_verdict()` — Bulk triage actions
- `uam_export_csv()` — CSV export via GraphQL
- `get_many()` — Parallel GET fan-out

## v1.1.0 — 2026-05-07

### New Features
- **Set Defaults Dialog** — Edit `isDefault`, `expiration`, `unlimitedExpiration`, and `unlimitedLicenses` on accounts/sites/groups in the backup file before restoring
- **Default Site Override** — When restoring a site marked as default, detects existing default sites and prompts to override (with rename)
- **Smart Site Resolution** — When a site name doesn't match on the destination, detects broken/zombie sites (404), offers to map to the existing default site instead of failing
- **Live Restore Progress** — Shows step-by-step detail during resolve and element restore
- **Connection Validation** — Backup now verifies the console connection before starting
- **Auto-open Reports** — Exported HTML/Excel reports open automatically

### Fixes
- **0-node Backup Warning** — Shows warning instead of false success
- **Shortened Error Messages** — Prevents UI overflow
- **Site Update API** — Added `update_site` method

## v1.0.1 — 2026-05-06
- Fixed sidebar width, centered window on launch
- Fixed Windows help button rendering
- Fixed paste button text
- Build improvements: xattr quarantine removal, auto-DMG creation

## v1.0.0 — 2026-05-06
- Initial release
- Full backup & restore for 26 element types
- Dual console connections with paste-from-ticket
- Mangle rename, auto-create sites/groups
- SKU mismatch detection and auto-fix
- HTML/Excel/JSON report generation
- 14 operations pages
- macOS & Windows builds via GitHub Actions
