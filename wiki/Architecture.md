# Architecture

## Project Structure

```
s1-command-center/
├── main.py              # Entry point
├── app.py               # Main window, sidebar, connections page, CLI output console
├── pages.py             # Backup & Restore pages, progress table, set-defaults dialog
├── pages_extra.py       # 16 operations pages (agents, threats, Purple AI, UAM, etc.)
├── agent_migrator.py    # Agent Migration: what to move → check → migrate (console or site-token file)
├── restore_compare.py   # Restore: backup vs destination comparison and renames before restoring
├── migration_guide.py   # The migration guide: steps, progress per console pair, sidebar / strip / hand-off
├── s1_api.py            # SentinelOne API client (REST + GraphQL)
├── config.py            # Configuration/context manager (saved connections)
├── export_utils.py      # HTML, Excel, JSON report generation
├── requirements.txt     # Python dependencies
├── s1cc.ico             # Application icon
├── build_macos.sh       # macOS build script (PyInstaller)
└── build_windows.bat    # Windows build script (PyInstaller)
```

## Module Responsibilities

### `app.py` — Main Application
- `App` class — main window, sidebar navigation, CLI output console
- `ConnectionsPage` — SOURCE/DESTINATION connection management
- `cli_log()` — global logging function used by all pages
- `run_async()` — background thread wrapper for API calls
- `LogBox` — styled text output widget
- Sidebar with scrollable nav, SRC/DST status indicators

### `pages.py` — Core Migration
- `BackupPage` — full backup workflow with progress table
- `RestorePage` — restore with mangle rename, SKU fix, auto-create
- `ProgressTable` — live-updating table with color-coded status
- `SetDefaultsDialog` — edit backup file properties before restore
- Element whitelists, scope helpers, field stripping for restore

### `restore_compare.py` — Compare with the destination

Shows, before a restore writes anything, what it will do with every
account, site and group in its scope — and lets the operator rename
backup scopes so they land where they should. Plain Python above the
window class, tested in `tests/test_restore_compare.py`.

- **`read_destination()`** reads the active accounts, then the sites and
  groups of only the accounts a backup account can land in (same name,
  same name in another case, or the ticket's account ID), plus an
  any-state lookup for each backup account name that isn't active — an
  expired or deleted account still holds its name. Reads only; a failure
  is raised, never turned into an empty destination.
- **`RestoreComparison`** decides each scope the way
  `RestorePage._resolve_dest_id` will: exact names, active sites only, the
  first of duplicate names, the ticket's account ID steering accounts and
  sites but not groups, nothing created for a level that isn't ticked, the
  default-site questions. States: *same, near, new, create, chosen,
  blocked, waiting*. Scopes outside the restore still count when a rename
  is checked, so a rename can never merge two backup scopes.
- **`rename_in_backup()`** writes the renames the way Mangle Rename does —
  the path of every node under the scope, and the renamed node's own
  record — parents first, so `_restore_scope` and the resolver read the
  new names.
- **`RestoreCompareDialog`** is `_NameFixDialog` with the restore's
  wording, marks and colours: the Fix names window keeps its text in class
  attributes and small methods (`_intro`, `_count_bits`, `_pick_note`, …)
  so both comparisons share one pooled tree and one layout. A rename that
  points at a destination account nobody read yet reads it in the
  background.

### `agent_migrator.py` — Agent Migration

Moves agents between consoles so that each SOURCE group's agents land in
the **same-named** destination group, using that group's own registration
token — or, with no API access to the destination, the tokens in a
site-token file. One screen of three `_StepCard`s — **What to move →
Check → Migrate** — each gated on the one before, with the results in
tabs (Plan, Agents, API calls, Status report) underneath.

Everything above the UI classes is a plain function, so the logic is
testable without a display (`tests/test_agent_migrator.py`,
`tests/test_agent_site_tokens.py`). The same files also drive the real
page end-to-end against fake consoles.

| Step | Function | What it does |
|------|----------|--------------|
| 2 | `read_destination()` | Reads only the destination accounts whose names match the source accounts in scope — and, with a site filter, only the sites of those names — through `build_scope_map()` (sites fetched in parallel), then re-applies the recorded name fixes (`apply_renames()`). |
| 2 | `build_match_plan()` | Walks the SOURCE and pairs each group with its same-named destination twin. **Sends nothing.** Two passes: the first pairs everything using the agent count the group listing already returns, so the plan appears at once; `refine_plan_counts()` then corrects those counts with one read per group, in parallel. |
| 2 | `build_file_plan()` | The same plan shape from a site-token file (`parse_site_tokens()`): each source site paired with the row of the file that names it, so step 3, the reports and the scheduler work unchanged. |
| 3 | `run_live_migration()` | Sends `move-to-console` per ready group with that group's token, then reads each agent back (`verify_migration()`) to report what actually happened. Streams events so the UI can show each machine. |

Key details:
- **`move-to-console` answers with a count, not per-agent results.** The
  read-back is the only way to tell "the console accepted 400 agents"
  from "400 agents moved", so *moved / pending / failed* are per machine
  and a rejected batch stamps every agent in it with the console's own
  error.
- **No dry-run switch.** Step 2 cannot move anything; step 3 moves
  exactly the ready rows step 2 listed and its button names the count.
- **A plan runs once, and only while it is current.** The page keeps the
  inputs a plan was made from (`_plan_inputs`: source, destination,
  scope, file). Any change locks step 3 until the next check, and so does
  a finished run (`_report`), so a second run always starts from a fresh
  look at what is left. `_refresh_gates()` is the one place step and
  button states are decided.
- **Name fixes are scoped and sticky.** A fix records the account/site
  path it applies to (`rename_in_map(..., within=)`), so same-named
  groups in different sites are told apart, and every later destination
  read re-applies it. A renamed map entry keeps the destination's own
  name in `dest_name`, so the plan's *Lands in* shows the real name.
- **`NameComparison` sits behind Fix names.** It is plain Python, with no
  widgets and no API calls. It turns the checked plan and the destination
  map into the source tree (account › site › group). Each node has a
  state, the destination candidates in its parent scope (with the source
  scope each one already pairs with), a reason, and where else its name
  appears. It also enforces that a destination scope is never picked
  twice. `_NameFixDialog` draws it with `_NameTree`, a pooled
  `_VirtualTable`, so a large source costs the same 60 rows.
- **The plan is cached** to `~/.s1-command-center/agent_match_plan.json`,
  fingerprinted on source console + scope + destination map hash, and
  restored on open only for the same two consoles. Registration tokens
  are *not* written to it — they are re-derived from the last destination
  read, `agent_destination_map.json`, which is written owner-only (`0600`)
  because it holds them.
- **Site-token files are refused, not guessed.** Ambiguous names, tokens
  for the source console, and sites listed twice with different tokens
  are reported with the reason before a single agent moves.

### `migration_guide.py` — The migration guide

Replaced the Migration Runbook page: instead of a checklist the operator
has to remember to open, the steps follow them through the migration.

- `STEPS` — the nine steps in migration order (connect, backup,
  pre-flight, preview, restore, validate, check the agents, migrate the
  agents, manifest), each naming the page it is done on and the click
  that does it. `GUIDED_PAGES` is the MIGRATION nav order they imply.
- `observe(app)` — reads what the pages already show, once a second:
  attributes only, never a console or a file. A result made against
  another destination doesn't count. Work still running —
  `BackupPage._timer_running`, `RestorePage._run_mode`, `_preflighting`
  and `_previewing`, `ValidationPage._running`, `AgentMigratorPage._busy`
  — outranks whatever its last run left behind.
- `Guide` — no widgets, so it is tested on its own. A step is done when
  the pages show it, once they have (the first sighting is remembered), or
  when ticked by hand. *attention* (a failed pre-flight, a stopped or
  failed restore) outranks an earlier success until redone or ticked;
  *running* outranks both and is never remembered or ticked, and a step
  run again keeps its place in the count. `update()` returns the
  hand-offs to show; `gate_message()` says what to warn about before
  restoring unchecked or migrating agents unvalidated — once per
  migration.
- `GuideStore` — progress per SOURCE → DESTINATION pair in
  `~/.s1-command-center/migration_guide.json`, written owner-only, with
  console names and timestamps but no tokens.
- `GuideController` — puts it on screen: the sidebar marks and *N of 9*
  bar, the next-step card and checklist, the strip above migration pages,
  the hand-off toast and **Show me** (it blinks the first control on
  screen and enabled, then puts it back unless the page restyled it).
  `RestorePage._start_restore` and `AgentMigratorPage._run_live` call
  `allow()` before their own confirmation. Every update goes through
  `_put()`, which skips unchanged options, and nothing repaints unless
  the state changed: a full repaint holds the main loop for at most
  12 ms.

### `pages_extra.py` — Operations
- 16 page classes, one per feature
- Each page follows the same pattern: header → filters → buttons → results table
- `ResultTable` — generic scrollable table for any dict-based data
- `PurpleAIPage` — natural language queries with suggestion buttons
- `UnifiedAlertsPage` — GraphQL alert triage with facets and pagination

### `s1_api.py` — API Client
- `S1API` class with 60+ methods
- Connection pooling (`HTTPAdapter`, pool of 32)
- Unified retry with 429/5xx + `Retry-After` support
- Parallel fan-out (`get_many()` via ThreadPoolExecutor)
- GraphQL transport (`_gql()`) for Purple AI and UAM
- See [[API Client]] for full details

### `config.py` — Configuration
- `ConfigManager` — loads/saves `~/.s1-command-center/contexts.json`
- `Context` — dataclass for a console connection (name, URL, token, role)
- Role management: each context can be `source`, `destination`, or unassigned

### `export_utils.py` — Report Generation
- `export_report()` — unified export to HTML, Excel, or JSON
- Dark-themed HTML template with summary cards and sortable tables
- Auto-opens generated reports in the default browser

## Design Patterns

### Async UI Pattern
All API calls use `run_async()`:
```python
def run_async(widget, fn, done=None, err=None):
    # Runs fn() in a daemon thread
    # Calls done(result) or err(exception) on the main thread via widget.after()
```

This keeps the GUI responsive during long operations.

### Console Proxy
Pages access the global output console via `_ConsoleProxy`:
```python
self.log = _ConsoleProxy(self.app)
self.log.log("message")
self.log.clear()
```

### Keeping the UI Alive Under Load

CustomTkinter widgets are expensive: each one draws onto its own canvas,
and `configure()` on a **visible** widget calls `update_idletasks()`
inside `_draw()`, which re-enters itself and redraws the whole window.
Measured on the Agent Migration page, a single visible `CTkLabel`
reconfigure costs **34–68 ms**. Creating widgets is worse still.

So for anything that updates while work is running:

1. **Never create a widget per row of data.** Build a fixed pool of
   reusable rows once and re-label them (`_VirtualTable` — behind the plan
   list, the live feed, the status report and the file-rows dialog — and
   `_Stats`). A run of 5,000 agents uses the same 60 rows as a run of 50.
   The old per-row match list took **32 s** to show 100 plan rows.
2. **Use plain `tk.Label` / `tk.Frame` for dense, frequently-updated
   cells.** They don't queue canvas redraws. Use `_hex()` to resolve a
   CustomTkinter `(light, dark)` colour pair to the single hex string Tk
   needs. This was the single biggest win (~4×).
3. **Guard every update.** Keep a signature of what a widget currently
   shows and skip `configure()` when nothing changed.
4. **Repaint per batch, not per event.** `_EventPump` carries events from
   the worker thread on a timer; the handler updates *state only* and
   drawing happens once per tick via its `on_flush` callback.
5. **Buffer text output.** `_CommandLog.add()` queues lines and
   `flush()` writes them in one insert.
6. **Never size a list by what the console holds.** Ask for one bounded
   page and let the API search (`S1API.search_accounts` /
   `search_sites`); `get_accounts`/`get_sites` walk every cursor page,
   which is right for a backup and wrong for a picker.

Rule 1 matters most inside a `CTkScrollableFrame`, where adding children
is **superlinear** — every insert relayouts the whole tree. Measured
while building the scope chooser:

| Rows added | Time to open | One keystroke |
|---|---|---|
| 50 | 2.3 s | 0.2 s |
| 200 | 112 s | 10 s |
| 400 | 874 s | 14 s |

Rebuilt as a fixed pool of 50 plain-Tk rows inside a `tk.Canvas`, with
the console doing the searching, it opens in **~0.6 s and re-renders in
~10 ms regardless of console size** — the widget count is constant at 51.
A picker that grows widgets per result does not degrade gracefully; it
stops working.

To find a stall, sample the main thread rather than guessing:

```python
# from a daemon thread, every ~5 ms
frame = sys._current_frames()[threading.main_thread().ident]
samples[traceback.extract_stack(frame)[-3:]] += 1
```

Samples dominated by `mainloop` with no application frames mean the cost
is Tk redrawing work queued by earlier `configure()` calls — not the
Python you are timing.

Two layout traps that come with plain-Tk cells and full-window pages:

- **Plain Tk doesn't follow CustomTkinter's scaling.** The app scales its
  widgets with the window (up to 1.35×), so `_VirtualTable` sizes its
  fonts in pixels and overrides `_set_scaling()` to re-size fonts, row
  height and fixed column widths whenever the scale changes.
- **Turn off propagation before building a page.** CustomTkinter flushes
  geometry while widgets are created, so `grid_propagate(False)` called
  at the end of `__init__` freezes whatever height the page had asked for
  by then — 752 px for Agent Migration, which pushed the app's status bar
  off a 700 px window. Call it first and let the results area absorb the
  slack.

### Page Registration
Pages are registered in `app.py` `_build()`:
```python
nav_ops = [
    ("Accounts & Sites", AccountsSitesPage),
    ("Agents", AgentsPage),
    ...
]
```

Each page class must accept `(master, app)` and optionally implement `on_show()`.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **GUI Framework** | CustomTkinter (dark theme) |
| **HTTP Client** | requests + HTTPAdapter |
| **Threading** | threading + concurrent.futures |
| **Data Format** | JSON (backup/config), GraphQL (Purple AI, UAM) |
| **Reports** | HTML template, openpyxl (Excel) |
| **Build** | PyInstaller |
| **CI/CD** | GitHub Actions |
