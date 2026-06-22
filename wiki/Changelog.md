# Changelog

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
