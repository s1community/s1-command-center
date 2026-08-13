# Changelog

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
