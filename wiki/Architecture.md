# Architecture

## Project Structure

```
s1-command-center/
├── main.py              # Entry point
├── app.py               # Main window, sidebar, connections page, CLI output console
├── pages.py             # Backup & Restore pages, progress table, set-defaults dialog
├── pages_extra.py       # 16 operations pages (agents, threats, Purple AI, UAM, etc.)
├── agent_migrator.py    # Agent Migration: map destination → match scopes → migrate live
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

### `agent_migrator.py` — Agent Migration

Moves agents between consoles so that each SOURCE group's agents land in
the **same-named** destination group, using that group's own registration
token. A guided three-step flow, gated so step N needs step N-1.

Everything above the UI classes is a plain function, so the logic is
testable without a display (`tests/test_agent_migrator.py`).

| Step | Function | What it does |
|------|----------|--------------|
| 1 | `build_scope_map()` | Walks the DESTINATION (accounts → sites → groups) and writes the scopes and their registration tokens to a JSON map file. Sites fetched in parallel. |
| 2 | `build_match_plan()` | Walks the SOURCE and pairs each scope with its same-named destination twin. **Sends nothing.** Two passes: the first pairs everything using the agent count the group listing already returns, so the plan appears at once; `refine_plan_counts()` then corrects those counts with one read per group, in parallel. |
| 3 | `run_live_migration()` | Sends `move-to-console` per group with that group's token, then reads each agent back (`verify_migration()`) to report what actually happened. Streams events so the UI can show each machine. |

Key details:
- **`move-to-console` answers with a count, not per-agent results.** The
  read-back is the only way to tell "the console accepted 400 agents"
  from "400 agents moved", so *moved / pending / failed* are per machine
  and a rejected batch stamps every agent in it with the console's own
  error.
- **No dry-run switch.** Step 2 cannot move anything; step 3 moves
  exactly the rows step 2 listed and its button names the count.
- **The plan is cached** to `~/.s1-command-center/agent_match_plan.json`,
  fingerprinted on source console + scope + map file hash, so reopening
  the app doesn't re-walk the console. Registration tokens are *not*
  written to the cache — they are re-derived from the map on load.
- Name mismatches between consoles are the usual reason a scope is
  skipped, so each blocked row says why and offers `rename_in_map()`.

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
   reusable rows once and re-label them (`_LiveFeed`, `_Stats`). A run of
   20,000 agents uses the same 40 rows as a run of 200.
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
