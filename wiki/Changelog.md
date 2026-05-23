# Changelog

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
