"""
The migration guide: the runbook that follows the operator.

The old Migration Runbook was a page of its own — a checklist that only
helped when someone remembered to open it. The guide puts the same steps
where the work happens:

- the MIGRATION panel in the sidebar marks each page ✓ / ● / ! and ends
  in a NEXT card that says what to do and goes there;
- a strip above every migration page names the next step, on that page
  or another;
- a toast hands over to the next step the moment one finishes;
- Restore without Pre-flight or Preview, and moving agents before the
  destination has been validated, ask once per migration.

Progress is read from the pages themselves wherever the app can see it,
and remembered per source → destination pair in ``migration_guide.json``
(console names and timestamps only), so a migration that runs over
several days doesn't start again at step 1 after a restart.
"""
import json
import os
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from tkinter import messagebox

import customtkinter as ctk

import config
import theme

GUIDE_FILE = "migration_guide.json"


@dataclass(frozen=True)
class Step:
    key: str
    title: str        # the NEXT card, the strip and the toast
    short: str        # the sidebar checklist
    page: str         # the nav label of the page the step is done on
    hint: str         # what to do, in a sentence or two
    action: str       # the click, in a few words, for the strip
    done_text: str    # the toast headline once it is done
    live_only: bool = False   # a current fact, never remembered or ticked


STEPS = (
    Step("connect", "Connect both consoles", "Connect consoles",
         "Connections",
         "Add the SOURCE and DESTINATION consoles and Save & Connect each.",
         "add SOURCE and DESTINATION, then Save & Connect each",
         "Both consoles connected", live_only=True),
    Step("backup", "Back up the source", "Back up the source",
         "Backup Source",
         "Pick the scope and elements, then click ▶ Start Backup.",
         "click ▶ Start Backup",
         "Backup saved"),
    Step("preflight", "Run the pre-flight check", "Pre-flight check",
         "Restore to Dest",
         "Load the backup, then click ✈ Pre-flight. It checks the "
         "destination and the token, and only reads.",
         "load the backup, then click ✈ Pre-flight (it only reads)",
         "Pre-flight passed"),
    Step("preview", "Preview the changes", "Preview changes",
         "Restore to Dest",
         "Click 🔍 Preview changes: a dry run of what the restore will "
         "create. Nothing is written.",
         "click 🔍 Preview changes (nothing is written)",
         "Preview finished"),
    Step("restore", "Restore to the destination", "Restore",
         "Restore to Dest",
         "Keep 📸 Snapshot first on and click ▶ Restore. The snapshot lets "
         "you ↩ Rollback.",
         "keep 📸 Snapshot first on and click ▶ Restore",
         "Restore finished"),
    Step("validate", "Validate the migration", "Validate",
         "Migration Validation",
         "Click ▶ Run Validation to compare SOURCE and DESTINATION across "
         "every element.",
         "click ▶ Run Validation",
         "Validation finished"),
    Step("agents_matched", "Check which agents move", "Check the agents",
         "Agent Migration",
         "Say what to move, then click 🔍 Check what will move. Nothing is "
         "sent.",
         "click 🔍 Check what will move (nothing is sent)",
         "Agent plan ready"),
    Step("agents_moved", "Migrate the agents", "Migrate the agents",
         "Agent Migration",
         "Click ▶ Migrate. Agents that are offline move on their next "
         "check-in.",
         "click ▶ Migrate",
         "Agents migrated"),
    Step("manifest", "Manifest & close the ticket", "Manifest & ticket",
         "Migration Validation",
         "Click 🧾 Migration Manifest. The PSO ticket comment is copied to "
         "your clipboard.",
         "click 🧾 Migration Manifest",
         "Manifest exported"),
)
STEP_KEYS = tuple(step.key for step in STEPS)
GUIDED_PAGES = tuple(dict.fromkeys(step.page for step in STEPS))
_BY_KEY = {step.key: step for step in STEPS}

_GATE_TITLES = {"restore": "Restore without checking first?",
                "agents": "Migrate the agents before validating?"}
_GATE_LINES = {
    "preflight": "✈ Pre-flight — the destination is reachable and the "
                 "token is valid and scoped wide enough.",
    "preview": "🔍 Preview changes — a dry run listing what the restore "
               "will create and what already exists.",
}

# What one look at the pages found for a step: status is "done",
# "attention", "running" or ""; token tells one result from the next;
# note says why.
Seen = namedtuple("Seen", "status token note", defaults=("", "", ""))


def guide_path() -> str:
    return os.path.join(config.CONFIG_DIR, GUIDE_FILE)


def console_id(url) -> str:
    text = str(url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.rstrip("/")


def route_key(source_url, dest_url) -> str:
    """One migration = one source → destination pair; "" until both are
    known."""
    src, dst = console_id(source_url), console_id(dest_url)
    return f"{src} → {dst}" if src and dst else ""


def _url(api) -> str:
    return str(getattr(api, "base_url", "") or "")


def _same(a, b) -> bool:
    return bool(console_id(a)) and console_id(a) == console_id(b)


def route_of(app) -> str:
    return route_key(_url(getattr(app, "source_api", None)),
                     _url(getattr(app, "dest_api", None)))


def _choice(page) -> str:
    """The console a page's SOURCE / DESTINATION menu is set to."""
    var = getattr(page, "_console_var", None)
    try:
        return str(var.get()) if var is not None else ""
    except Exception:
        return ""


def observe(app) -> dict:
    """What the pages show right now, step by step: {key: Seen}.

    Reads attributes only — never a console or a file — so it is cheap
    enough to run every second. A result made against another destination
    doesn't count for this one."""
    src_url = _url(getattr(app, "source_api", None))
    dst_url = _url(getattr(app, "dest_api", None))
    pages = getattr(app, "pages", None) or {}
    seen = {}
    if src_url and dst_url:
        seen["connect"] = Seen("done")

    path = getattr(app, "_last_backup_path", None)
    taken_from = getattr(app, "_last_backup_url", "")
    if path and (not taken_from or _same(taken_from, src_url)):
        seen["backup"] = Seen("done", str(path))

    restore = pages.get("Restore to Dest")
    check = getattr(restore, "_last_preflight", None) or {}
    if check and _same(check.get("dest"), dst_url):
        token = str(check.get("at") or "")
        if check.get("verdict") == "fail":
            seen["preflight"] = Seen(
                "attention", token,
                "Pre-flight found problems — fix what it flagged, then run "
                "✈ Pre-flight again.")
        else:
            seen["preflight"] = Seen(
                "done", token,
                "It passed with warnings — read them before restoring."
                if check.get("verdict") == "warn" else "")
    preview = getattr(restore, "_last_preview", None) or {}
    if preview and _same(preview.get("dest"), dst_url):
        seen["preview"] = Seen("done", str(preview.get("at") or ""))
    run = getattr(restore, "_report_meta", None) or {}
    if run.get("end_time") and _same(run.get("dest_url"), dst_url):
        token = str(run["end_time"])
        if run.get("run_failed"):
            seen["restore"] = Seen(
                "attention", token,
                "The restore stopped with an error — read the log, then run "
                "it again or ↻ Resume.")
        elif run.get("cancelled"):
            seen["restore"] = Seen(
                "attention", token,
                "The restore was stopped — ↻ Resume carries on where it "
                "left off.")
        else:
            seen["restore"] = Seen("done", token)

    validation = pages.get("Migration Validation")
    vmeta = getattr(validation, "_meta", None) or {}
    if getattr(validation, "_results", None) and _same(vmeta.get("dst_url"),
                                                       dst_url):
        seen["validate"] = Seen("done", str(vmeta.get("when") or ""))
    manifest = getattr(validation, "_manifest_exported", None) or {}
    if manifest and (not manifest.get("dest")
                     or _same(manifest.get("dest"), dst_url)):
        seen["manifest"] = Seen("done", str(manifest.get("at") or ""))

    agents = pages.get("Agent Migration")
    plan = getattr(agents, "_plan", None)
    if plan:
        try:
            stale = bool(agents._plan_stale())
        except Exception:
            stale = False
        if not stale:
            seen["agents_matched"] = Seen(
                "done", str(getattr(agents, "_plan_saved_at", "")
                            or id(plan)))
    report = getattr(agents, "_report", None)
    if report is not None:
        seen["agents_moved"] = Seen("done", str(id(report)))

    backup = pages.get("Backup Source")
    busy = getattr(agents, "_busy", None)
    running = {
        "backup": (getattr(backup, "_timer_running", False)
                   and _choice(backup) == "SOURCE"),
        "preflight": getattr(restore, "_preflighting", False),
        "preview": getattr(restore, "_previewing", False),
        "restore": (getattr(restore, "_run_mode", "") == "running"
                    and _same(run.get("dest_url"), dst_url)),
        "validate": getattr(validation, "_running", False),
        "agents_matched": busy == "check",
        "agents_moved": busy == "live",
    }
    for key, now in running.items():
        if now:
            seen[key] = Seen("running")
    return seen


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fresh() -> dict:
    return {"steps": {}, "gates": {}, "baseline": {}}


class GuideStore:
    """Every migration's progress, keyed by source → destination, in one
    owner-only JSON file. Holds console names and timestamps — no tokens."""

    MAX_ROUTES = 40

    def __init__(self, path: str = ""):
        self.path = path or guide_path()
        self.routes = self._read()

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        routes = data.get("routes") if isinstance(data, dict) else None
        if not isinstance(routes, dict):
            return {}
        return {key: rec for key, rec in routes.items()
                if isinstance(key, str) and isinstance(rec, dict)}

    def record(self, route: str) -> dict:
        rec = self.routes.setdefault(route, {})
        for part in ("steps", "gates", "baseline"):
            if not isinstance(rec.get(part), dict):
                rec[part] = {}
        return rec

    def save(self):
        if len(self.routes) > self.MAX_ROUTES:
            keep = sorted(self.routes, reverse=True,
                          key=lambda r: str(self.routes[r].get("updated", "")))
            self.routes = {r: self.routes[r] for r in keep[:self.MAX_ROUTES]}
        folder = os.path.dirname(self.path)
        tmp = self.path + ".tmp"
        try:
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "routes": self.routes}, f,
                          indent=2, ensure_ascii=False)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except OSError:
            pass


class Guide:
    """Where a migration stands. No widgets, so it is tested on its own.

    A step is done when the pages show it done, or once they have — the
    first sighting is remembered for the pair of consoles — or when the
    operator ticks it. "attention" (a failed pre-flight, a stopped
    restore) outranks an earlier success until it is redone or ticked.
    "running" outranks both, and is never remembered or ticked."""

    def __init__(self, store=None):
        self.store = store if store is not None else GuideStore()
        self.route = ""
        self._loose = _fresh()      # progress made before both consoles
        self._raw = {}
        self._seen = {}
        self._prev = None           # statuses at the last look; None = quiet

    def _rec(self) -> dict:
        return self.store.record(self.route) if self.route else self._loose

    def _save(self, rec):
        if self.route:
            rec["updated"] = _now()
            self.store.save()

    def update(self, route: str, seen: dict) -> list:
        """Take in a look at the pages. Returns what just finished or
        needs a look, as ("done" | "attention", key) pairs — none on the
        first look, or when the consoles change to another pair."""
        dirty = False
        if route != self.route:
            if self.route and route:
                self._prev = None
            elif route:
                rec = self.store.record(route)
                for part in ("steps", "gates"):
                    for key, value in self._loose[part].items():
                        if key not in rec[part]:
                            rec[part][key] = value
                            dirty = True
            self._loose = _fresh()
            self.route = route
        rec = self._rec()
        baseline = rec["baseline"]
        self._raw = dict(seen)
        current = {}
        for step in STEPS:
            got = seen.get(step.key) or Seen()
            if got.status and got.token and baseline.get(step.key) == \
                    got.token:
                got = Seen()
            current[step.key] = got
        events = []
        quiet = self._prev is None
        for step in STEPS:
            key, got = step.key, current[step.key]
            before = None if quiet else self._prev.get(key)
            if got.status == "done":
                known = key in rec["steps"]
                if not step.live_only and not known:
                    rec["steps"][key] = {"at": _now(), "how": "auto"}
                    dirty = True
                if not quiet and before != "done" and (
                        step.live_only or not known or before == "running"):
                    events.append(("done", key))
            elif got.status == "attention" and not quiet and \
                    before != "attention":
                events.append(("attention", key))
        self._seen = current
        self._prev = {key: got.status for key, got in current.items()}
        if dirty:
            self._save(rec)
        return events

    def state(self, key: str) -> str:
        """"running", "attention", "done" or "todo"."""
        got = self._seen.get(key) or Seen()
        if got.status in ("running", "attention", "done"):
            return got.status
        if not _BY_KEY[key].live_only and key in self._rec()["steps"]:
            return "done"
        return "todo"

    def finished(self, key: str) -> bool:
        """Done — or running again after it was done, which doesn't take
        it off the count."""
        state = self.state(key)
        return state == "done" or (
            state == "running" and not _BY_KEY[key].live_only
            and key in self._rec()["steps"])

    def note(self, key: str) -> str:
        return (self._seen.get(key) or Seen()).note

    def how(self, key: str) -> str:
        """"live" (the pages show it), "auto", "manual" or ""."""
        if (self._seen.get(key) or Seen()).status == "done":
            return "live"
        steps = self._rec()["steps"]
        if key not in steps:
            return ""
        entry = steps[key]
        return str(entry.get("how") or "auto") if isinstance(entry, dict) \
            else "auto"

    def next(self):
        return next((step for step in STEPS
                     if not self.finished(step.key)), None)

    def running(self):
        return next((step for step in STEPS
                     if self.state(step.key) == "running"), None)

    def focus(self):
        """The step to put in front of the operator: the one running,
        else the next one to do."""
        return self.running() or self.next()

    def done_count(self) -> int:
        return sum(self.finished(step.key) for step in STEPS)

    def complete(self) -> bool:
        return self.next() is None

    def page_mark(self, page: str) -> tuple:
        """(text, tone) beside a page in the sidebar."""
        steps = [step for step in STEPS if step.page == page]
        if not steps:
            return "", ""
        states = [self.state(step.key) for step in steps]
        if "running" in states:
            return "…", "run"
        if "attention" in states:
            return "!", "warn"
        done = sum(self.finished(step.key) for step in steps)
        if done == len(steps):
            return "✓", "done"
        upcoming = self.next()
        if upcoming is not None and upcoming.page == page:
            return (f"{done}/{len(steps)}" if done else "●"), "next"
        return (f"{done}/{len(steps)}" if done else ""), \
            ("part" if done else "")

    def mark(self, key: str, done: bool = True):
        """Tick a step by hand (done elsewhere, or deliberately skipped),
        or take a tick back. Ticking a problem puts that result to rest."""
        if _BY_KEY[key].live_only:
            return
        rec = self._rec()
        if done:
            rec["steps"][key] = {"at": _now(), "how": "manual"}
            raw = self._raw.get(key)
            if raw and raw.status == "attention" and raw.token:
                rec["baseline"][key] = raw.token
                self._seen[key] = Seen()
        else:
            rec["steps"].pop(key, None)
        self._save(rec)

    def acknowledge(self, gate: str):
        rec = self._rec()
        rec["gates"][gate] = _now()
        self._save(rec)

    def gate_message(self, gate: str) -> str:
        """What to say before a risky step, or "" when nothing is
        missing, or the operator already chose to go ahead."""
        if not self.route or gate in self._rec()["gates"]:
            return ""
        if gate == "restore":
            if self.finished("restore"):
                return ""
            missing = [k for k in ("preflight", "preview")
                       if not self.finished(k)]
            if not missing:
                return ""
            lines = "\n".join(f"•  {_GATE_LINES[k]}" for k in missing)
            both = len(missing) == 2
            return (f"Not done yet for this migration:\n\n{lines}\n\n"
                    f"{'Both only read' if both else 'It only reads'} — "
                    f"nothing is written to either console.\n\n"
                    f"Restore anyway? Choose No to run "
                    f"{'them' if both else 'it'} first.")
        if gate == "agents":
            if self.finished("validate"):
                return ""
            lead = ("Nothing has been restored to the destination for this "
                    "migration yet, and it hasn't been validated."
                    if not self.finished("restore") else
                    "The destination hasn't been validated for this "
                    "migration yet.")
            return (f"{lead}\n\n▶ Run Validation (Migration Validation "
                    f"page) compares SOURCE and DESTINATION across every "
                    f"element — agents should land where their policies, "
                    f"exclusions and groups are already in place.\n\n"
                    f"Migrate the agents anyway? Choose No to validate "
                    f"first.")
        return ""

    def gate_step(self, gate: str):
        keys = ("preflight", "preview") if gate == "restore" else \
            ("validate",)
        return next((k for k in keys if not self.finished(k)), None)

    def start_over(self):
        """Count the steps again for this pair of consoles. Results the
        pages still show don't count until they are made again."""
        rec = self._rec()
        baseline = dict(rec["baseline"])
        for key, got in self._raw.items():
            if got.status and got.token:
                baseline[key] = got.token
        rec["baseline"] = baseline
        rec["steps"] = {}
        rec["gates"] = {}
        self._seen = {key: (Seen() if got.status and got.token else got)
                      for key, got in self._seen.items()}
        self._save(rec)

    def signature(self) -> tuple:
        return (self.route,
                tuple((self.state(k), self.note(k), self.how(k))
                      for k in STEP_KEYS))


# ═══════════════════════════════════════════════════════════════════════
#  On screen
# ═══════════════════════════════════════════════════════════════════════

_UNSET = object()
_TONES = {"done": theme.GREEN, "next": theme.BRAND_LIGHT,
          "warn": theme.WARN, "part": theme.TEXT_FAINT, "run": theme.INFO}
_RUNNING_HINT = "Still running — the guide moves on by itself once it " \
                "finishes."
CARD_WRAP = 176
_BAR_RESERVE = 330


def _put(widget, **opts):
    """configure() only what changed since the guide last set it — every
    configure() on a visible CTk widget redraws it."""
    cache = widget.__dict__.setdefault("_guide_opts", {})
    todo = {k: v for k, v in opts.items() if cache.get(k, _UNSET) != v}
    if todo:
        widget.configure(**todo)
        cache.update(todo)


def _grid_shown(widget, visible):
    if visible and not widget.winfo_manager():
        widget.grid()
    elif not visible and widget.winfo_manager():
        widget.grid_remove()


def _mapped(widget) -> bool:
    try:
        return bool(widget.winfo_ismapped())
    except Exception:
        return False


def _enabled(widget) -> bool:
    try:
        return widget.cget("state") != "disabled"
    except Exception:
        return True


def _ghost(parent, text, command, **kw):
    opts = dict(text=text, command=command, height=28,
                font=(theme.UI_FONT, 11), fg_color=theme.GHOST,
                hover_color=theme.GHOST_HOVER, text_color=theme.TEXT_MUTED,
                border_width=1, border_color=theme.BORDER,
                corner_radius=theme.RADIUS_SM)
    opts.update(kw)
    return ctk.CTkButton(parent, **opts)


# The control a step is done with, best first: the first one on screen and
# enabled is the one "Show me" lights up.
_TARGETS = {
    "backup": ("Backup Source", ("_start_btn",)),
    "preflight": ("Restore to Dest", ("_preflight_btn", "_browse_btn")),
    "preview": ("Restore to Dest", ("_preview_btn", "_browse_btn")),
    "restore": ("Restore to Dest",
                ("_resume_btn", "_start_btn", "_browse_btn")),
    "validate": ("Migration Validation", ("_run_btn",)),
    "agents_matched": ("Agent Migration", ("check_btn",)),
    "agents_moved": ("Agent Migration", ("live_btn", "check_btn")),
    "manifest": ("Migration Validation", ("_manifest_btn", "_run_btn")),
}


class GuideController:
    """Puts the guide on screen — the sidebar marks and NEXT card, the
    strip above migration pages, the hand-off toast — and asks before the
    risky steps. Built into the main window by App._build."""

    POLL_MS = 1000
    TOAST_MS = 12000

    def __init__(self, app, store=None):
        self.app = app
        self.guide = Guide(store)
        self._page = ""
        self._started = False
        self._interval = 0
        self._sig = None
        self._failed = False
        self._marks = {}
        self._count = None
        self._progress = None
        self._card = None
        self._bar = None
        self._toast = None
        self._list_open = False
        self._dismissed = ""
        self._pending = None
        self._toast_job = None
        self._flashing = set()
        self._wrap_w = 0

    # ── building ──────────────────────────────────────────────────────
    def build_header(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(row, text="MIGRATION", font=(theme.UI_FONT, 10, "bold"),
                     text_color=theme.BRAND_LIGHT, anchor="w").pack(
            side="left")
        self._count = ctk.CTkLabel(row, text="", anchor="e",
                                   font=(theme.UI_FONT, 10, "bold"),
                                   text_color=theme.TEXT_FAINT)
        self._count.pack(side="right")
        self._progress = ctk.CTkProgressBar(parent, height=4,
                                            corner_radius=2)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=14, pady=(4, 6))

    def add_nav_mark(self, page, label):
        self._marks[page] = label

    def build_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=theme.CARD,
                            corner_radius=theme.RADIUS_MD, border_width=1,
                            border_color=theme.BORDER)
        card.pack(fill="x", padx=10, pady=(8, 2))
        card.grid_columnconfigure(0, weight=1)
        eyebrow = ctk.CTkLabel(card, text="", anchor="w", height=14,
                               font=(theme.UI_FONT, 9, "bold"),
                               text_color=theme.BRAND_LIGHT)
        eyebrow.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        title = ctk.CTkLabel(card, text="", anchor="w", justify="left",
                             font=(theme.UI_FONT, 13, "bold"),
                             text_color=theme.TEXT, wraplength=CARD_WRAP)
        title.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 0))
        hint = ctk.CTkLabel(card, text="", anchor="w", justify="left",
                            font=(theme.UI_FONT, 11),
                            text_color=theme.TEXT_MUTED, wraplength=CARD_WRAP)
        hint.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 10))
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 10))
        go = ctk.CTkButton(btns, text="Go ▸", width=76, height=28,
                           font=(theme.UI_FONT, 12, "bold"),
                           fg_color=theme.BRAND, hover_color=theme.BRAND_HOVER,
                           corner_radius=theme.RADIUS_SM,
                           command=lambda: self.go())
        go.grid(row=0, column=0, padx=(0, 6))
        mark = _ghost(btns, "Mark done", self.mark_next, width=86)
        mark.grid(row=0, column=1)
        again = _ghost(btns, "Start over", self.start_over, width=96)
        again.grid(row=0, column=2)
        again.grid_remove()

        toggle = ctk.CTkButton(
            parent, text=f"All {len(STEPS)} steps  ▸", anchor="w", height=24,
            font=(theme.UI_FONT, 11), fg_color="transparent",
            hover_color=theme.SIDEBAR_HOVER, text_color=theme.TEXT_MUTED,
            corner_radius=theme.RADIUS_SM, command=self.toggle_list)
        toggle.pack(fill="x", padx=10, pady=(2, 0))
        steps = ctk.CTkFrame(parent, fg_color="transparent")
        rows = []
        for step in STEPS:
            row = ctk.CTkFrame(steps, fg_color="transparent")
            row.pack(fill="x")
            glyph = ctk.CTkLabel(row, text="○", width=18,
                                 font=(theme.UI_FONT, 11, "bold"),
                                 text_color=theme.TEXT_FAINT)
            glyph.pack(side="left", padx=(4, 2))
            flip = _ghost(row, "Mark", lambda k=step.key: self.flip(k),
                          width=48, height=22, font=(theme.UI_FONT, 10))
            flip.pack(side="right", padx=(2, 2))
            name = ctk.CTkButton(
                row, text=step.short, anchor="w", height=24,
                font=(theme.UI_FONT, 11), fg_color="transparent",
                hover_color=theme.SIDEBAR_HOVER, text_color=theme.TEXT_MUTED,
                corner_radius=theme.RADIUS_SM,
                command=lambda k=step.key: self.go(k))
            name.pack(side="left", fill="x", expand=True)
            rows.append({"glyph": glyph, "flip": flip, "name": name})
        restart = ctk.CTkButton(
            steps, text="Start over…", anchor="w", height=22,
            font=(theme.UI_FONT, 10), fg_color="transparent",
            hover_color=theme.SIDEBAR_HOVER, text_color=theme.TEXT_FAINT,
            corner_radius=theme.RADIUS_SM, command=self.start_over)
        restart.pack(fill="x", padx=(24, 0), pady=(2, 4))
        self._card = {"frame": card, "eyebrow": eyebrow, "title": title,
                      "hint": hint, "btns": btns, "go": go, "mark": mark,
                      "again": again, "toggle": toggle, "steps": steps,
                      "rows": rows}

    def build_bar(self, parent, before=None):
        bar = ctk.CTkFrame(parent, fg_color=theme.MIG_PANEL,
                           corner_radius=theme.RADIUS_MD, border_width=1,
                           border_color=theme.MIG_BORDER)
        bar.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(bar, text="", font=(theme.UI_FONT, 10, "bold"),
                             text_color=theme.BRAND_LIGHT)
        badge.grid(row=0, column=0, sticky="w", padx=(14, 10), pady=8)
        text = ctk.CTkLabel(bar, text="", anchor="w", justify="left",
                            font=(theme.UI_FONT, 12), text_color=theme.TEXT)
        text.grid(row=0, column=1, sticky="ew", pady=8)
        go = ctk.CTkButton(bar, text="Show me", width=128, height=28,
                           font=(theme.UI_FONT, 12, "bold"),
                           fg_color=theme.BRAND, hover_color=theme.BRAND_HOVER,
                           corner_radius=theme.RADIUS_SM,
                           command=lambda: self.go())
        go.grid(row=0, column=2, padx=(10, 4))
        close = ctk.CTkButton(bar, text="✕", width=28, height=28,
                              font=(theme.UI_FONT, 12), fg_color="transparent",
                              hover_color=theme.SIDEBAR_HOVER,
                              text_color=theme.TEXT_FAINT,
                              corner_radius=theme.RADIUS_SM,
                              command=self.dismiss)
        close.grid(row=0, column=3, padx=(2, 8))
        bar.bind("<Configure>", self._wrap_bar, add="+")
        self._bar = {"frame": bar, "badge": badge, "text": text, "go": go,
                     "before": before, "shown": False}

    def build_toast(self, parent, over):
        toast = ctk.CTkFrame(parent, fg_color=theme.CARD_ELEVATED,
                             corner_radius=theme.RADIUS_MD, border_width=1,
                             border_color=theme.GREEN)
        toast.grid_columnconfigure(0, weight=1)
        head = ctk.CTkLabel(toast, text="", anchor="w",
                            font=(theme.UI_FONT, 13, "bold"),
                            text_color=theme.GREEN)
        head.grid(row=0, column=0, sticky="ew", padx=(14, 4), pady=(10, 0))
        close = ctk.CTkButton(toast, text="✕", width=24, height=24,
                              font=(theme.UI_FONT, 11), fg_color="transparent",
                              hover_color=theme.SIDEBAR_HOVER,
                              text_color=theme.TEXT_FAINT,
                              corner_radius=theme.RADIUS_SM,
                              command=self.hide_toast)
        close.grid(row=0, column=1, padx=(0, 8), pady=(8, 0))
        body = ctk.CTkLabel(toast, text="", anchor="w", justify="left",
                            font=(theme.UI_FONT, 12),
                            text_color=theme.TEXT_MUTED, wraplength=290)
        body.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14,
                  pady=(2, 10))
        go = ctk.CTkButton(toast, text="Go ▸", width=96, height=28,
                           font=(theme.UI_FONT, 12, "bold"),
                           fg_color=theme.BRAND, hover_color=theme.BRAND_HOVER,
                           corner_radius=theme.RADIUS_SM,
                           command=self._toast_go)
        go.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 12))
        self._toast = {"frame": toast, "head": head, "body": body, "go": go,
                       "over": over, "step": None}

    # ── running ───────────────────────────────────────────────────────
    def start(self, interval=POLL_MS):
        """Begin watching. Called once the consoles are connected, so the
        first look doesn't announce the start-up as progress."""
        self._started = True
        self._interval = interval
        self.refresh(force=True)
        if interval:
            self.app.after(interval, self._tick)

    def _tick(self):
        try:
            self.refresh()
        except Exception as exc:
            if not self._failed:
                self._failed = True
                log = getattr(self.app, "cli_log", None)
                if callable(log):
                    log(f"Migration guide: {exc}", "warning")
        self.app.after(self._interval, self._tick)

    def on_page(self, label):
        self._page = label
        self.refresh()

    def refresh(self, force=False):
        if not self._started:
            return
        events = self.guide.update(route_of(self.app), observe(self.app))
        sig = (self.guide.signature(), self._page, self._dismissed,
               self._list_open)
        if force or sig != self._sig:
            self._sig = sig
            self._paint()
        if events:
            self._pending = events
        if self._pending and not getattr(self.app, "_busy", False):
            pending, self._pending = self._pending, None
            self._show_toast(pending)

    # ── actions ───────────────────────────────────────────────────────
    def go(self, key=None):
        """Open the page a step is done on and light up its control — or,
        while it runs, just open the page to watch it."""
        step = _BY_KEY.get(key) if key else self.guide.focus()
        if step is None or getattr(self.app, "_busy", False):
            return
        running = self.guide.state(step.key) == "running"
        if self._page != step.page:
            self.app._show(step.page)
            if not running:
                self.app.after(300, lambda k=step.key: self.flash_step(k))
        elif not running:
            self.flash_step(step.key)

    def mark_next(self):
        step = self.guide.focus()
        if step is not None and not step.live_only and \
                self.guide.state(step.key) != "running":
            self.guide.mark(step.key)
            self.refresh(force=True)

    def flip(self, key):
        self.guide.mark(key, self.guide.state(key) != "done")
        self.refresh(force=True)

    def dismiss(self):
        step = self.guide.focus()
        self._dismissed = step.key if step is not None else ""
        self.refresh(force=True)

    def toggle_list(self):
        if self._card is None:
            return
        self._list_open = not self._list_open
        steps, toggle = self._card["steps"], self._card["toggle"]
        if self._list_open:
            steps.pack(fill="x", padx=10, pady=(0, 4), after=toggle)
        else:
            steps.pack_forget()
        _put(toggle, text=f"All {len(STEPS)} steps  "
                          f"{'▾' if self._list_open else '▸'}")
        self.refresh(force=True)

    def start_over(self):
        route = self.guide.route
        where = f" for\n{route}" if route else ""
        if not messagebox.askyesno(
                "Start the guide over?",
                f"Count the migration steps again from the start{where}?"
                "\n\nNothing on either console changes. Results the pages "
                "still show are counted again only once they are redone."):
            return
        self.guide.start_over()
        self._dismissed = ""
        self.refresh(force=True)

    def allow(self, gate) -> bool:
        """Ask once per migration before a risky step. True = go ahead."""
        message = self.guide.gate_message(gate) if self._started else ""
        if not message:
            return True
        if messagebox.askyesno(_GATE_TITLES.get(gate, "Continue?"), message,
                               icon="warning"):
            self.guide.acknowledge(gate)
            self.refresh(force=True)
            return True
        self.point_at(self.guide.gate_step(gate))
        return False

    def point_at(self, key):
        step = _BY_KEY.get(key) if key else None
        if step is not None and step.page == self._page:
            self.flash_step(step.key)
        elif self._bar is not None and self._bar["shown"]:
            self.flash(self._bar["go"])
        elif self._card is not None:
            self.flash(self._card["go"])

    def flash_step(self, key):
        self.flash(self._target(key))

    def _target(self, key):
        pages = getattr(self.app, "pages", None) or {}
        if key == "connect":
            conn = pages.get("Connections")
            found = []
            for api_attr, card_attr in (("source_api", "src_card"),
                                        ("dest_api", "dst_card")):
                card = getattr(conn, card_attr, None)
                if getattr(self.app, api_attr, None) is None and \
                        isinstance(card, dict):
                    found.append(card.get("frame"))
        else:
            page, names = _TARGETS.get(key, ("", ()))
            holder = pages.get(page)
            found = [getattr(holder, name, None) for name in names]
        found = [w for w in found if w is not None and _mapped(w)]
        enabled = [w for w in found if _enabled(w)]
        return (enabled or found or [None])[0]

    def flash(self, widget, times=6, every=230):
        """Blink a control's outline a few times, then put it back —
        unless its page restyled it meanwhile."""
        if widget is None or id(widget) in self._flashing:
            return
        try:
            rest = (widget.cget("border_width"), widget.cget("border_color"))
        except Exception:
            return
        lit = (3, theme.WARN)
        self._flashing.add(id(widget))

        def tick(n):
            try:
                now = (widget.cget("border_width"),
                       widget.cget("border_color"))
                if now not in (rest, lit):
                    self._flashing.discard(id(widget))
                    return
                look = rest if n >= times or n % 2 else lit
                if now != look:
                    widget.configure(border_width=look[0],
                                     border_color=look[1])
                if n >= times:
                    self._flashing.discard(id(widget))
                    return
            except Exception:
                self._flashing.discard(id(widget))
                return
            self.app.after(every, lambda: tick(n + 1))

        tick(0)

    # ── the hand-off ──────────────────────────────────────────────────
    def _show_toast(self, events):
        toast = self._toast
        if toast is None:
            return
        kind, key = next((e for e in events if e[0] == "attention"),
                         events[-1])
        step = _BY_KEY[key]
        upcoming = self.guide.next()
        target = None
        if kind == "attention":
            head, tone = "⚠  Needs a look", theme.WARN
            body = self.guide.note(key) or f"{step.title} needs a look."
            target = step
        else:
            head, tone = f"✓  {step.done_text}", theme.GREEN
            note = self.guide.note(key)
            lead = f"{note}\n" if note else ""
            if upcoming is None:
                body = (f"{lead}All {len(STEPS)} steps are done — the "
                        f"migration is complete.")
            else:
                where = ("on this page" if upcoming.page == self._page
                         else f"on {upcoming.page}")
                body = f"{lead}Next: {upcoming.title} — {where}."
                target = upcoming
        _put(toast["head"], text=head, text_color=tone)
        _put(toast["body"], text=body)
        _put(toast["frame"], border_color=tone)
        toast["step"] = target.key if target is not None else None
        _grid_shown(toast["go"], target is not None)
        if target is not None:
            _put(toast["go"],
                 text="Show me" if target.page == self._page else "Go ▸")
        toast["frame"].place(in_=toast["over"], relx=1.0, rely=1.0,
                             x=-20, y=-20, anchor="se")
        toast["frame"].lift()
        if self._toast_job is not None:
            try:
                self.app.after_cancel(self._toast_job)
            except Exception:
                pass
        self._toast_job = self.app.after(self.TOAST_MS, self.hide_toast)

    def hide_toast(self):
        self._toast_job = None
        if self._toast is not None and self._toast["frame"].winfo_manager():
            self._toast["frame"].place_forget()

    def _toast_go(self):
        key = self._toast["step"] if self._toast is not None else None
        self.hide_toast()
        if key:
            self.go(key)

    # ── painting ──────────────────────────────────────────────────────
    def _paint(self):
        upcoming = self.guide.focus()
        self._paint_header()
        for page, label in self._marks.items():
            text, tone = self.guide.page_mark(page)
            _put(label, text=text,
                 text_color=_TONES.get(tone, theme.TEXT_FAINT))
        self._paint_card(upcoming)
        self._paint_list(upcoming)
        self._paint_bar(upcoming)

    def _paint_header(self):
        if self._count is None:
            return
        done, total = self.guide.done_count(), len(STEPS)
        _put(self._count, text=f"{done} of {total}",
             text_color=theme.GREEN if done == total else theme.TEXT_FAINT)
        if self._progress is not None:
            if getattr(self._progress, "_guide_done", None) != done:
                self._progress._guide_done = done
                self._progress.set(done / total)
            _put(self._progress, progress_color=(
                theme.GREEN if done == total else theme.BRAND))

    def _paint_card(self, upcoming):
        card = self._card
        if card is None:
            return
        total = len(STEPS)
        if upcoming is None:
            _put(card["eyebrow"], text="ALL DONE", text_color=theme.GREEN)
            _put(card["title"], text="Migration complete")
            _put(card["hint"], text=f"All {total} steps are done for this "
                                    f"pair of consoles. Start over for the "
                                    f"next wave or migration.")
            _put(card["frame"], border_color=theme.GREEN)
            _grid_shown(card["go"], False)
            _grid_shown(card["mark"], False)
            _grid_shown(card["again"], True)
            _grid_shown(card["btns"], True)
            return
        n = STEP_KEYS.index(upcoming.key) + 1
        state = self.guide.state(upcoming.key)
        here = upcoming.page == self._page
        if state == "running":
            eyebrow, tone, border = "RUNNING", theme.INFO, theme.INFO
            hint = _RUNNING_HINT
        elif state == "attention":
            eyebrow, tone, border = "NEEDS A LOOK", theme.WARN, theme.WARN
            hint = self.guide.note(upcoming.key)
        else:
            eyebrow, tone, border = "NEXT", theme.BRAND_LIGHT, theme.BORDER
            hint = upcoming.hint
        _put(card["eyebrow"], text=f"{eyebrow} · STEP {n} OF {total}",
             text_color=tone)
        _put(card["title"], text=upcoming.title)
        _put(card["hint"], text=hint)
        _put(card["frame"], border_color=border)
        _put(card["go"], text="Show me" if here else "Go ▸")
        show_go = not (state == "running" and here)
        show_mark = not upcoming.live_only and state != "running"
        _grid_shown(card["go"], show_go)
        _grid_shown(card["mark"], show_mark)
        _grid_shown(card["again"], False)
        _grid_shown(card["btns"], show_go or show_mark)

    def _paint_list(self, upcoming):
        if self._card is None or not self._list_open:
            return
        for step, row in zip(STEPS, self._card["rows"]):
            state = self.guide.state(step.key)
            is_next = upcoming is not None and step.key == upcoming.key
            if state == "running":
                glyph, tone = "…", theme.INFO
            elif state == "done":
                glyph, tone = "✓", theme.GREEN
            elif state == "attention":
                glyph, tone = "!", theme.WARN
            elif is_next:
                glyph, tone = "●", theme.BRAND_LIGHT
            else:
                glyph, tone = "○", theme.TEXT_FAINT
            _put(row["glyph"], text=glyph, text_color=tone)
            _put(row["name"],
                 text_color=theme.TEXT if is_next else theme.TEXT_MUTED)
            flippable = (not step.live_only and state != "running"
                         and self.guide.how(step.key) != "live")
            if flippable:
                _put(row["flip"], text="Undo" if state == "done" else "Mark")
                if not row["flip"].winfo_manager():
                    row["flip"].pack(side="right", padx=(2, 2),
                                     before=row["name"])
            elif row["flip"].winfo_manager():
                row["flip"].pack_forget()

    def _paint_bar(self, upcoming):
        bar = self._bar
        if bar is None:
            return
        show = (upcoming is not None and self._page in GUIDED_PAGES
                and self._dismissed != upcoming.key)
        if show:
            n = STEP_KEYS.index(upcoming.key) + 1
            state = self.guide.state(upcoming.key)
            here = upcoming.page == self._page
            if state == "running":
                badge, tone, border = "RUNNING", theme.INFO, theme.INFO
                text = (f"{upcoming.title} — still running…" if here else
                        f"{upcoming.title} — still running on "
                        f"{upcoming.page}.")
            elif state == "attention":
                badge, tone, border = "NEEDS A LOOK", theme.WARN, theme.WARN
                text = self.guide.note(upcoming.key)
            else:
                badge, tone = "NEXT", theme.BRAND_LIGHT
                border = theme.MIG_BORDER
                text = (f"{upcoming.title} — {upcoming.action}." if here
                        else f"{upcoming.title} — on {upcoming.page}.")
            _put(bar["badge"], text=f"{badge} · {n}/{len(STEPS)}",
                 text_color=tone)
            _put(bar["text"], text=text)
            _put(bar["go"], text="Show me" if here else "Take me there ▸")
            _grid_shown(bar["go"], not (state == "running" and here))
            _put(bar["frame"], border_color=border)
        if show != bar["shown"]:
            if show:
                where = ({"before": bar["before"]}
                         if bar["before"] is not None else {})
                bar["frame"].pack(side="top", fill="x", padx=20,
                                  pady=(14, 0), **where)
            else:
                bar["frame"].pack_forget()
            bar["shown"] = show

    def _wrap_bar(self, event):
        """Wrap the strip's text to the room the buttons leave. Only a
        real change of width re-wraps, so it can't chase itself."""
        label = self._bar["text"]
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(label)
        except Exception:
            scale = 1.0
        width = max(160, int(event.width / scale) - _BAR_RESERVE)
        if abs(width - self._wrap_w) >= 8:
            self._wrap_w = width
            label.configure(wraplength=width)
