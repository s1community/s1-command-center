# Architecture

## Project Structure

```
s1-command-center/
├── main.py              # Entry point
├── app.py               # Main window, sidebar, connections page, CLI output console
├── pages.py             # Backup & Restore pages, progress table, set-defaults dialog
├── pages_extra.py       # 16 operations pages (agents, threats, Purple AI, UAM, etc.)
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
- `AgentMigrationPage` — cross-console agent migration
- `ProgressTable` — live-updating table with color-coded status
- `SetDefaultsDialog` — edit backup file properties before restore
- Element whitelists, scope helpers, field stripping for restore

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
