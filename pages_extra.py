"""
Extra feature pages: Agents, Threats, Users, Activities, Deep Visibility,
Exclusions/Blocklist, STAR, Applications/CVEs, Ranger, Remote Scripts, Raw API,
Accounts/Sites, Threat Intel, Tags.
"""
import customtkinter as ctk
import json
import time
from tkinter import messagebox, filedialog
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import (run_async, LogBox, CARD, GREEN, GREEN_HOVER, ACCENT,
                 ACCENT_HOVER, WARN, WARN_HOVER, INFO, cli_log,
                 _ConsoleProxy, _help_btn, UI_FONT, MONO_FONT, BRAND,
                 BRAND_HOVER, CARD_ELEVATED, BORDER, NEUTRAL, NEUTRAL_HOVER,
                 TEXT, TEXT_MUTED, TEXT_FAINT, SIDEBAR_BG, CONSOLE_BG)
from export_utils import export_report


# ═══════════════════════════════════════════════════════════════════════
#  Helper: scrollable result table
# ═══════════════════════════════════════════════════════════════════════

class ResultTable(ctk.CTkScrollableFrame):
    """Generic scrollable list that shows dicts as rows."""

    def __init__(self, master, columns: list[str], **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        super().__init__(master, **kw)
        self.columns = columns
        self._rows: list[dict] = []
        self._header()

    def _header(self):
        for j, col in enumerate(self.columns):
            ctk.CTkLabel(self, text=col, font=(UI_FONT, 11, "bold"),
                         text_color=TEXT_MUTED).grid(
                row=0, column=j, padx=6, pady=(4, 2), sticky="w")

    def clear(self):
        for w in self.winfo_children():
            w.destroy()
        self._rows = []
        self._header()

    def add_row(self, data: dict, row_idx: Optional[int] = None):
        self._rows.append(data)
        r = row_idx if row_idx is not None else len(self._rows)
        for j, col in enumerate(self.columns):
            val = data.get(col, "")
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)[:60]
            else:
                val = str(val)[:60]
            ctk.CTkLabel(self, text=val, font=(UI_FONT, 11)).grid(
                row=r, column=j, padx=6, pady=1, sticky="w")

    def load(self, items: list[dict], batch_size: int = 50):
        self.clear()
        self._pending_items = list(items[:500])
        self._batch_size = batch_size
        self._load_next_batch()

    def _load_next_batch(self):
        for _ in range(min(self._batch_size, len(self._pending_items))):
            item = self._pending_items.pop(0)
            self.add_row(item, len(self._rows))
        if self._pending_items:
            self.after(1, self._load_next_batch)


def _pick_api(app, role="source"):
    api = app.source_api if role == "source" else app.dest_api
    if not api:
        cli_log(f"No {role.upper()} console connected. Go to Connections page first.", "error")
    return api


# ═══════════════════════════════════════════════════════════════════════
#  Accounts & Sites Page
# ═══════════════════════════════════════════════════════════════════════

class AccountsSitesPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Accounts & Sites",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Browse accounts → sites → groups hierarchy on the SOURCE console.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn_row, text="Load Hierarchy", height=36,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Fetch accounts, sites, and groups tree from SOURCE."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Export Report", height=36,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Export hierarchy as HTML/Excel/JSON."
                  ).pack(side="left", padx=(0, 8))
        self.count_lbl = ctk.CTkLabel(btn_row, text="",
                                      font=(UI_FONT, 12),
                                      text_color=TEXT_MUTED)
        self.count_lbl.pack(side="left", padx=8)

        self.tree = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12)
        self.tree.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))
        self._tree_data = []

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return
        cli_log("Fetching accounts, sites, and groups…", "cmd")

        def do():
            accounts = api.get_accounts()
            cli_log(f"Found {len(accounts)} accounts", "info")
            result = []
            for acct in accounts:
                aid = acct.get("id", "")
                aname = acct.get("name", "?")
                sites = api.get_sites(params={
                    "accountIds": aid, "states": "active",
                    "sortBy": "name", "sortOrder": "asc"})
                site_list = []
                for site in sites:
                    sid = site.get("id", "")
                    sname = site.get("name", "?")
                    groups = api.get_groups(params={
                        "siteIds": sid, "sortBy": "name", "sortOrder": "asc"})
                    site_list.append({
                        "name": sname, "id": sid,
                        "groups": [{"name": g.get("name", "?"),
                                    "id": g.get("id", "")} for g in groups]})
                result.append({"name": aname, "id": aid, "sites": site_list})
            return result

        def done(tree_data):
            self._tree_data = tree_data
            cli_log(f"Hierarchy loaded", "success")
            for w in self.tree.winfo_children():
                w.destroy()
            # flatten into render list for batched widget creation
            flat = []
            for acct in tree_data:
                flat.append(("acct", acct["name"], None))
                for site in acct["sites"]:
                    flat.append(("site", site["name"], site["id"]))
                    for grp in site["groups"]:
                        flat.append(("grp", grp["name"], None))
            self._tree_pending = flat
            self._tree_rendered = 0
            self._render_tree_batch()

        def _render_batch_inner():
            batch = self._tree_pending[:50]
            self._tree_pending = self._tree_pending[50:]
            for kind, name, nid in batch:
                if kind == "acct":
                    f = ctk.CTkFrame(self.tree, fg_color="transparent")
                    f.pack(fill="x", pady=(6, 0), padx=4)
                    ctk.CTkLabel(f, text=f"📁 {name}",
                                 font=(UI_FONT, 14, "bold"),
                                 text_color=GREEN).pack(anchor="w")
                elif kind == "site":
                    f = ctk.CTkFrame(self.tree, fg_color="transparent")
                    f.pack(fill="x", padx=24)
                    ctk.CTkLabel(f, text=f"🌐 {name}  (id={nid[:12]}…)",
                                 font=(UI_FONT, 12)).pack(anchor="w")
                else:
                    f = ctk.CTkFrame(self.tree, fg_color="transparent")
                    f.pack(fill="x", padx=48)
                    ctk.CTkLabel(f, text=f"📂 {name}",
                                 font=(UI_FONT, 11),
                                 text_color=TEXT_MUTED).pack(anchor="w")
                self._tree_rendered += 1
            if self._tree_pending:
                self.after(1, _render_batch_inner)
            else:
                self.count_lbl.configure(
                    text=f"{self._tree_rendered} nodes loaded")
                cli_log(f"{self._tree_rendered} total nodes "
                        f"(accounts + sites + groups)", "info")

        self._render_tree_batch = _render_batch_inner

        run_async(self, do, done)

    def _export(self):
        rows = []
        for acct in self._tree_data:
            for site in acct["sites"]:
                for grp in site["groups"]:
                    rows.append({"account": acct["name"], "accountId": acct["id"],
                                 "site": site["name"], "siteId": site["id"],
                                 "group": grp["name"], "groupId": grp.get("id", "")})
                if not site["groups"]:
                    rows.append({"account": acct["name"], "accountId": acct["id"],
                                 "site": site["name"], "siteId": site["id"],
                                 "group": "", "groupId": ""})
        cols = ["account", "accountId", "site", "siteId", "group", "groupId"]
        accts = len(self._tree_data)
        sites = sum(len(a["sites"]) for a in self._tree_data)
        stats = [{"label": "Accounts", "value": accts},
                 {"label": "Sites", "value": sites},
                 {"label": "Groups", "value": len(rows)}]
        export_report("Accounts & Sites", cols, rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Agents Page
# ═══════════════════════════════════════════════════════════════════════

class AgentsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.agents: list[dict] = []
        self.selected_ids: list[str] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Agents",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="List, search, and perform actions on agents.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # filters
        filt = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        filt.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        filt.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(filt, text="Name filter:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.name_entry = ctk.CTkEntry(filt, placeholder_text="Computer name contains…", height=32)
        self.name_entry.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(filt, text="Site filter:",
                     font=(UI_FONT, 13)).grid(
            row=1, column=0, padx=12, pady=8, sticky="w")
        self.site_entry = ctk.CTkEntry(filt, placeholder_text="(Optional) site name", height=32)
        self.site_entry.grid(row=1, column=1, padx=12, pady=8, sticky="ew")

        # buttons
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        self.list_btn = ctk.CTkButton(btn, text="List Agents", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._list)
        self.list_btn.pack(side="left", padx=(0, 4))
        self.count_btn = ctk.CTkButton(btn, text="Count", height=34,
                      command=self._count)
        self.count_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Init Scan", height=34,
                      fg_color=BRAND,
                      command=lambda: self._action("scan")).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Abort Scan", height=34,
                      fg_color=BRAND,
                      command=lambda: self._action("abort")).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Uninstall", height=34,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self._action("uninstall")).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "List: fetch agents with filters. Count: total count only. "
                  "Init/Abort Scan: trigger or cancel full disk scan. "
                  "Uninstall: queue agent removal. Export: save as report."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        # result list
        self.table = ResultTable(self,
                                 ["computerName", "osName", "agentVersion",
                                  "machineType", "isActive", "id"],
                                 height=300)
        self.table.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _read_filters(self):
        """Read widget values on the main thread (no API calls)."""
        return {
            "name": self.name_entry.get().strip(),
            "site": self.site_entry.get().strip(),
        }

    @staticmethod
    def _resolve_params(api, filters):
        """Build API params from pre-read filter values (safe for background thread)."""
        params = {}
        if filters["name"]:
            params["computerName__contains"] = filters["name"]
        if filters["site"]:
            sites = api.get_sites(params={"name": filters["site"]})
            if sites:
                params["siteIds"] = sites[0]["id"]
        return params

    def _list(self):
        api = _pick_api(self.app)
        if not api:
            return
        cli_log("Retrieving agents…", "cmd")
        filters = self._read_filters()
        self.list_btn.configure(state="disabled", text="Loading…")
        self.info_lbl.configure(text="Fetching…")

        def do():
            params = self._resolve_params(api, filters)
            return api.get_agents(params=params, max_items=500)

        def done(agents):
            self.list_btn.configure(state="normal", text="List Agents")
            self.agents = agents
            self.selected_ids = [a["id"] for a in agents]
            self.info_lbl.configure(text=f"{len(agents)} agents")
            self.table.load(agents)
            cli_log(f"Retrieved {len(agents)} agents", "success")
            for a in agents[:5]:
                cli_log(f"  {a.get('computerName','?')}  "
                        f"{a.get('osName','')}  v{a.get('agentVersion','?')}  "
                        f"active={a.get('isActive','?')}", "info")
            if len(agents) > 5:
                cli_log(f"  … and {len(agents)-5} more", "info")

        def fail(e):
            self.list_btn.configure(state="normal", text="List Agents")
            self.info_lbl.configure(text="Error")

        run_async(self, do, done, fail)

    def _count(self):
        api = _pick_api(self.app)
        if not api:
            return
        cli_log("Counting agents…", "cmd")
        filters = self._read_filters()
        self.count_btn.configure(state="disabled", text="Counting…")

        def do():
            params = self._resolve_params(api, filters)
            return api.get_agent_count(params)

        def done(c):
            self.count_btn.configure(state="normal", text="Count")
            self.info_lbl.configure(text=f"Count: {c}")
            cli_log(f"Agent count: {c}", "success")

        def fail(e):
            self.count_btn.configure(state="normal", text="Count")
            self.info_lbl.configure(text="Error")

        run_async(self, do, done, fail)

    def _action(self, action):
        api = _pick_api(self.app)
        if not api or not self.selected_ids:
            messagebox.showwarning("No agents", "List agents first.")
            return
        labels = {"scan": "initiate scan on", "abort": "abort scan on",
                  "uninstall": "UNINSTALL"}
        if not messagebox.askyesno("Confirm",
                                   f"{labels[action]} {len(self.selected_ids)} agent(s)?"):
            return
        cli_log(f"Sending '{action}' command to {len(self.selected_ids)} agents…", "cmd")

        def do():
            ids = self.selected_ids
            if action == "scan":
                api.initiate_scan(ids)
            elif action == "abort":
                api.abort_scan(ids)
            elif action == "uninstall":
                api.uninstall_agent(ids)
            return len(ids)

        def done(n):
            self.info_lbl.configure(text=f"{action} sent to {n} agents")
            cli_log(f"Sent command to queue '{action}' for {n} agents", "success")
            messagebox.showinfo("Done", f"{action} command queued for {n} agents.")

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Agents", "value": len(self.table._rows)}]
        export_report("Agents", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Threats Page
# ═══════════════════════════════════════════════════════════════════════

class ThreatsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Threats",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View threats, timeline, and notes from the SOURCE console.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load Threats", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load: fetch all threats. Timeline/Notes: enter a threat ID "
                  "first, then click to view its timeline or analyst notes."
                  ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(btn, text="Threat ID:", font=(UI_FONT, 13)).pack(side="left", padx=(16, 4))
        self.tid_entry = ctk.CTkEntry(btn, placeholder_text="for timeline/notes", width=200, height=32)
        self.tid_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Timeline", height=34,
                      command=self._timeline).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Notes", height=34,
                      command=self._notes).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12), text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["id", "classification", "agentComputerName",
                                  "mitigationStatus", "createdDate", "threatName"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return
        cli_log("Retrieving threats…", "cmd")

        def do():
            return api.get_threats(max_items=200)

        def done(threats):
            items = []
            for t in threats:
                ti = t.get("threatInfo", t)
                items.append({
                    "id": t.get("id", ""),
                    "classification": ti.get("classification", ""),
                    "agentComputerName": ti.get("agentComputerName",
                                                t.get("agentComputerName", "")),
                    "mitigationStatus": ti.get("mitigationStatus",
                                               t.get("mitigationStatus", "")),
                    "createdDate": ti.get("createdDate",
                                          t.get("createdAt", "")),
                    "threatName": ti.get("threatName",
                                         t.get("threatName", "")),
                })
            self.info_lbl.configure(text=f"{len(items)} threats")
            self.table.load(items)
            cli_log(f"Retrieved {len(items)} threats", "success")
            for t in items[:3]:
                cli_log(f"  {t.get('threatName','?')} on {t.get('agentComputerName','?')} — {t.get('mitigationStatus','')}", "info")
            if len(items) > 3:
                cli_log(f"  … and {len(items)-3} more", "info")

        run_async(self, do, done)

    def _timeline(self):
        api = _pick_api(self.app)
        tid = self.tid_entry.get().strip()
        if not api or not tid:
            messagebox.showwarning("Missing", "Enter a threat ID.")
            return

        def do():
            return api.get_threat_timeline(tid)

        def done(events):
            self.info_lbl.configure(text=f"{len(events)} timeline events")
            cli_log(f"Threat {tid}: {len(events)} timeline events", "success")
            cols = ["activityType", "primaryDescription",
                    "secondaryDescription", "createdAt"]
            self.table.columns = cols
            self.table.load(events)

        run_async(self, do, done)

    def _notes(self):
        api = _pick_api(self.app)
        tid = self.tid_entry.get().strip()
        if not api or not tid:
            messagebox.showwarning("Missing", "Enter a threat ID.")
            return

        def do():
            return api.get_threat_notes(tid)

        def done(notes):
            self.info_lbl.configure(text=f"{len(notes)} notes")
            cli_log(f"Threat {tid}: {len(notes)} notes", "success")
            cols = ["id", "text", "creator", "createdAt"]
            self.table.columns = cols
            self.table.load(notes)

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Threats", "value": len(self.table._rows)}]
        export_report("Threats", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Users & Roles Page
# ═══════════════════════════════════════════════════════════════════════

class UsersRolesPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.users = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Users & Roles",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Manage users, roles, and 2FA enrollment.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        filt = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        filt.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        filt.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(filt, text="Search:", font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.search_entry = ctk.CTkEntry(filt, placeholder_text="email or name…", height=32)
        self.search_entry.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="List Users", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._list_users).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="List Roles", height=34,
                      command=self._list_roles).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="My User", height=34,
                      command=self._my_user).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Token Details", height=34,
                      command=self._token_details).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Enroll 2FA (all unenrolled)", height=34,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._enroll_2fa).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "List Users/Roles: query console users or RBAC roles. "
                  "My User: show current token's user. Token Details: show "
                  "token scope/expiry. Enroll 2FA: enroll all unenrolled users."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12), text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["email", "fullName", "scope",
                                  "twoFaEnabled", "id"],
                                 height=300)
        self.table.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _list_users(self):
        api = _pick_api(self.app)
        if not api:
            return
        q = self.search_entry.get().strip()

        def do():
            params = {}
            if q:
                params["query"] = q
            return api.get_users(params=params, max_items=500)

        def done(users):
            self.users = users
            self.info_lbl.configure(text=f"{len(users)} users")
            cli_log(f"Retrieved {len(users)} users", "success")
            self.table.columns = ["email", "fullName", "scope",
                                  "twoFaEnabled", "id"]
            self.table.load(users)

        run_async(self, do, done)

    def _list_roles(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_roles()

        def done(roles):
            self.info_lbl.configure(text=f"{len(roles)} roles")
            cli_log(f"Retrieved {len(roles)} roles", "success")
            self.table.columns = ["name", "description", "id"]
            self.table.load(roles)

        run_async(self, do, done)

    def _my_user(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_my_user()

        def done(u):
            self.info_lbl.configure(
                text=f"{u.get('fullName', '?')} ({u.get('email', '?')})")
            cli_log(f"My user: {u.get('fullName','?')} ({u.get('email','?')})", "success")
            self.table.columns = ["fullName", "email", "scope",
                                  "twoFaEnabled", "id"]
            self.table.load([u])

        run_async(self, do, done)

    def _token_details(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_token_details(api.api_token)

        def done(details):
            d = details.get("data", details)
            self.info_lbl.configure(text="Token details loaded")
            self.table.columns = list(d.keys())[:6] if isinstance(d, dict) else ["data"]
            self.table.load([d] if isinstance(d, dict) else [{"data": d}])

        run_async(self, do, done)

    def _enroll_2fa(self):
        api = _pick_api(self.app)
        if not api:
            return
        if not messagebox.askyesno("Confirm 2FA",
                                   "Enroll all unenrolled users in 2FA?"):
            return

        def do():
            users = api.get_users(params={
                "twoFaEnabled": "false", "emailVerified": "true"})
            unenrolled = [u for u in users
                          if not u.get("twoFaConfigured")
                          and u.get("email") != "vigilance@sentinelone.com"]
            if not unenrolled:
                return 0
            ids = [u["id"] for u in unenrolled]
            api.enroll_2fa(ids)
            return len(ids)

        def done(n):
            self.info_lbl.configure(text=f"Enrolled {n} users in 2FA")
            cli_log(f"2FA enrollment sent to {n} users", "success")
            messagebox.showinfo("Done", f"2FA enrollment sent to {n} users.")

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Users", "value": len(self.table._rows)}]
        export_report("Users & Roles", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Activities Page
# ═══════════════════════════════════════════════════════════════════════

class ActivitiesPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Activities",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View activity log from the SOURCE console.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load Activities", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Activity Types", height=34,
                      command=self._types).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load Activities: fetch the console activity log. "
                  "Activity Types: list all known activity type IDs."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["activityType", "primaryDescription",
                                  "secondaryDescription", "createdAt"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_activities(max_items=500)

        def done(acts):
            self.info_lbl.configure(text=f"{len(acts)} activities")
            cli_log(f"Retrieved {len(acts)} activities", "success")
            self.table.columns = ["activityType", "primaryDescription",
                                  "secondaryDescription", "createdAt"]
            self.table.load(acts)

        run_async(self, do, done)

    def _types(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_activity_types()

        def done(types):
            self.info_lbl.configure(text=f"{len(types)} activity types")
            cli_log(f"Retrieved {len(types)} activity types", "success")
            self.table.columns = ["id", "action", "descriptionTemplate"]
            self.table.load(types)

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Activities", "value": len(self.table._rows)}]
        export_report("Activities", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Deep Visibility Page
# ═══════════════════════════════════════════════════════════════════════

class DeepVisibilityPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Deep Visibility",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Run Deep Visibility (S1QL) queries and view results.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="S1QL Query:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.query_entry = ctk.CTkEntry(card,
                                        placeholder_text='e.g. AgentName IS NOT EMPTY',
                                        height=32)
        self.query_entry.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(card, text="Hours back:",
                     font=(UI_FONT, 13)).grid(
            row=1, column=0, padx=12, pady=8, sticky="w")
        self.hours_entry = ctk.CTkEntry(card, placeholder_text="24", width=80, height=32)
        self.hours_entry.grid(row=1, column=1, padx=12, pady=8, sticky="w")

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Run Query", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._run).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Submit an S1QL query to Deep Visibility and poll for "
                  "results. Enter the query and how many hours back to search."
                  ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.log = _ConsoleProxy(self.app)

    def _run(self):
        api = _pick_api(self.app)
        if not api:
            return
        query = self.query_entry.get().strip()
        if not query:
            messagebox.showwarning("Missing", "Enter an S1QL query.")
            return
        hours = 24
        try:
            hours = int(self.hours_entry.get().strip() or "24")
        except ValueError:
            pass
        now = datetime.now(timezone.utc)
        from_dt = (now - timedelta(hours=hours)).isoformat()
        to_dt = now.isoformat()
        self.log.clear()
        self.log.log(f"Submitting DV query: {query}")
        self.info_lbl.configure(text="Running…")
        cli_log(f"Deep Visibility query: {query} (last {hours}h)", "cmd")

        def do():
            qid = api.dv_create_query(query, from_dt, to_dt)
            self.after(0, lambda: self.log.log(f"Query ID: {qid}"))
            # poll status
            for _ in range(120):
                st = api.dv_get_query_status(qid)
                status = st.get("responseState", "")
                if status == "FINISHED":
                    break
                time.sleep(2)
            events = api.dv_get_events(qid, max_items=500)
            return qid, events

        def done(result):
            qid, events = result
            self.info_lbl.configure(text=f"Done — {len(events)} events")
            self.log.log(f"Query complete: {len(events)} events returned")
            cli_log(f"DV query complete: {len(events)} events (queryId={qid})", "success")
            for ev in events[:50]:
                self.log.log(json.dumps(ev, default=str)[:200])
            if len(events) > 50:
                self.log.log(f"… and {len(events) - 50} more events")

        def fail(e):
            self.info_lbl.configure(text="Error")
            self.log.log(f"ERROR: {e}")

        run_async(self, do, done, fail)

    def _export(self):
        export_report("Deep Visibility", ["raw"], [{"raw": line} for line in self.log.get("1.0", "end").strip().split("\n") if line.strip()])

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Exclusions & Blocklist Page
# ═══════════════════════════════════════════════════════════════════════

class ExclusionsBlocklistPage(ctk.CTkFrame):
    EXCL_TYPES = ["white_hash", "path", "file_type", "certificate", "browser"]

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Exclusions & Blocklist",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View exclusions and blocklist entries from the SOURCE console.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)

        ctk.CTkLabel(btn, text="Type:", font=(UI_FONT, 13)).pack(
            side="left", padx=(0, 4))
        self.type_var = ctk.StringVar(value="path")
        ctk.CTkOptionMenu(btn, values=self.EXCL_TYPES,
                          variable=self.type_var, width=140,
                          height=34).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Load Exclusions", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load_excl).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Load Unified", height=34,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._load_unified).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Load Blocklist", height=34,
                      command=self._load_block).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load Exclusions: fetch legacy exclusions by selected type "
                  "(hash, path, file_type, cert, browser). "
                  "Load Unified: fetch all Unified Exclusions (v2.1) "
                  "including tag-based exclusions. "
                  "Load Blocklist: fetch SHA1 hash block entries."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["type", "value", "osType",
                                  "description", "id"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _load_excl(self):
        api = _pick_api(self.app)
        if not api:
            return
        et = self.type_var.get()

        def do():
            return api.get_exclusions({"tenant": "true"}, et)

        def done(items):
            self.info_lbl.configure(text=f"{len(items)} {et} exclusions")
            cli_log(f"Retrieved {len(items)} '{et}' exclusions", "success")
            self.table.columns = ["type", "value", "osType",
                                  "description", "id"]
            self.table.load(items)

        run_async(self, do, done)

    def _load_unified(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_unified_exclusions({"tenant": "true"})

        def done(items):
            self.info_lbl.configure(
                text=f"{len(items)} unified exclusions")
            cli_log(f"Retrieved {len(items)} unified exclusions", "success")
            self.table.columns = ["exclusionName", "type", "value",
                                  "osType", "modeType", "id"]
            self.table.load(items)

        run_async(self, do, done)

    def _load_block(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_blocklist({"tenant": "true"})

        def done(items):
            self.info_lbl.configure(text=f"{len(items)} blocklist entries")
            cli_log(f"Retrieved {len(items)} blocklist entries", "success")
            self.table.columns = ["value", "source", "osType",
                                  "description", "id"]
            self.table.load(items)

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Items", "value": len(self.table._rows)}]
        export_report("Exclusions & Blocklist", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  STAR Rules Page
# ═══════════════════════════════════════════════════════════════════════

class STARRulesPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="STAR Rules",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View and manage Custom Detection (STAR) rules.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load STAR Rules", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export to JSON", height=34,
                      command=self._export_json).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Import from JSON", height=34,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._import).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load: fetch Custom Detection (STAR) rules. "
                  "Export to JSON: save rules as raw JSON for backup. "
                  "Import from JSON: create rules from a JSON file."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["name", "status", "severity",
                                  "s1ql", "id"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))
        self._rules = []

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_star_rules({"tenant": "true"})

        def done(rules):
            self._rules = rules
            self.info_lbl.configure(text=f"{len(rules)} STAR rules")
            self.table.load(rules)
            cli_log(f"Retrieved {len(rules)} STAR rules", "success")
            for r in rules[:3]:
                cli_log(f"  {r.get('name','?')} [{r.get('status','?')}] severity={r.get('severity','?')}", "info")
            if len(rules) > 3:
                cli_log(f"  … and {len(rules)-3} more", "info")

        run_async(self, do, done)

    def _export_json(self):
        if not self._rules:
            messagebox.showwarning("No data", "Load STAR rules first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Export STAR rules",
            initialfile=f"star-rules-{datetime.now():%Y%m%d-%H%M}.json")
        if not path:
            return
        with open(path, "w") as f:
            json.dump(self._rules, f, indent=2, default=str)
        messagebox.showinfo("Done", f"Exported {len(self._rules)} rules to {path}")

    def _import(self):
        api = _pick_api(self.app)
        if not api:
            return
        fp = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            title="Import STAR rules from file")
        if not fp:
            return
        with open(fp, "r") as f:
            rules = json.load(f)
        if not isinstance(rules, list):
            rules = [rules]
        if not messagebox.askyesno("Confirm",
                                   f"Import {len(rules)} STAR rule(s) to SOURCE console?"):
            return

        def do():
            ok = 0
            for rule in rules:
                try:
                    api.create_star_rule({"tenant": "true"}, rule)
                    ok += 1
                except Exception:
                    pass
            return ok

        def done(n):
            self.info_lbl.configure(text=f"Imported {n}/{len(rules)} rules")
            cli_log(f"Imported {n}/{len(rules)} STAR rules", "success")
            messagebox.showinfo("Done", f"Imported {n} STAR rules.")

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total STAR Rules", "value": len(self.table._rows)}]
        export_report("STAR Rules", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Applications & CVEs Page
# ═══════════════════════════════════════════════════════════════════════

class ApplicationsCVEsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Applications & CVEs",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View installed applications and associated vulnerabilities.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load Applications", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load_apps).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Risky Apps (CVEs)", height=34,
                      fg_color=WARN, text_color="black",
                      command=self._load_risky).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load Applications: list installed apps. "
                  "Risky Apps: filter apps with known CVEs."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["name", "version", "publisher",
                                  "riskLevel", "installedDate"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _load_apps(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_applications(max_items=500)

        def done(apps):
            self.info_lbl.configure(text=f"{len(apps)} applications")
            self.table.columns = ["name", "version", "publisher",
                                  "riskLevel", "installedDate"]
            self.table.load(apps)
            cli_log(f"Retrieved {len(apps)} installed applications", "success")

        def fail(e):
            code = getattr(e, "status_code", 0)
            self.info_lbl.configure(text=f"Error ({code})" if code else f"Error: {e}")
            cli_log(f"Applications endpoint error: {e}", "warning")

        run_async(self, do, done, fail)

    def _load_risky(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_applications(params={
                "riskLevels": "low,medium,high,critical"}, max_items=200)

        def done(apps):
            self.info_lbl.configure(text=f"{len(apps)} risky applications")
            cli_log(f"Retrieved {len(apps)} risky applications (with CVEs)", "success")
            self.table.columns = ["name", "version", "publisher",
                                  "riskLevel", "installedDate"]
            self.table.load(apps)

        def fail(e):
            code = getattr(e, "status_code", 0)
            self.info_lbl.configure(text=f"Error ({code})" if code else f"Error: {e}")
            cli_log(f"Risky apps endpoint error: {e}", "warning")

        run_async(self, do, done, fail)

    def _export(self):
        stats = [{"label": "Total Applications", "value": len(self.table._rows)}]
        export_report("Applications & CVEs", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Threat Intel Page
# ═══════════════════════════════════════════════════════════════════════

class ThreatIntelPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Threat Intelligence",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Manage IOCs (Indicators of Compromise) — view, add, delete.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # add IOC card
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(1, weight=1)
        for i, (lbl, ph) in enumerate([
            ("Source:", "e.g. MyFeed"),
            ("Type:", "DNS|SHA1|SHA256|MD5|IPV4|IPV6|URL"),
            ("Value:", "IOC value"),
            ("External ID:", "optional ext. identifier"),
        ]):
            ctk.CTkLabel(card, text=lbl, font=(UI_FONT, 13)).grid(
                row=i, column=0, padx=12, pady=4, sticky="w")
        self.ioc_source = ctk.CTkEntry(card, placeholder_text="e.g. MyFeed", height=30)
        self.ioc_source.grid(row=0, column=1, padx=12, pady=4, sticky="ew")
        self.ioc_type = ctk.CTkOptionMenu(card,
                                          values=["DNS", "SHA1", "SHA256", "MD5",
                                                  "IPV4", "IPV6", "URL"],
                                          width=140, height=30)
        self.ioc_type.grid(row=1, column=1, padx=12, pady=4, sticky="w")
        self.ioc_value = ctk.CTkEntry(card, placeholder_text="IOC value", height=30)
        self.ioc_value.grid(row=2, column=1, padx=12, pady=4, sticky="ew")
        self.ioc_ext = ctk.CTkEntry(card, placeholder_text="optional", height=30)
        self.ioc_ext.grid(row=3, column=1, padx=12, pady=4, sticky="ew")

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="List IOCs", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._list).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Add IOC", height=34,
                      fg_color=BRAND,
                      command=self._add).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "List IOCs: fetch threat intelligence indicators. "
                  "Add IOC: create a new IOC entry (fill fields above)."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["source", "type", "value",
                                  "method", "validUntil"],
                                 height=250)
        self.table.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _list(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_threat_intel(max_items=500)

        def done(iocs):
            self.info_lbl.configure(text=f"{len(iocs)} IOCs")
            self.table.load(iocs)
            cli_log(f"Retrieved {len(iocs)} threat intel IOCs", "success")

        run_async(self, do, done)

    def _add(self):
        api = _pick_api(self.app)
        if not api:
            return
        src = self.ioc_source.get().strip()
        itype = self.ioc_type.get()
        val = self.ioc_value.get().strip()
        ext_id = self.ioc_ext.get().strip() or val
        if not src or not val:
            messagebox.showwarning("Missing", "Fill source and value.")
            return

        def do():
            expiration = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            ioc = {
                "source": src, "type": itype, "value": val,
                "externalId": ext_id, "method": "EQUALS",
                "validUntil": expiration,
            }
            return api.upsert_threat_intel({"tenant": "true"}, [ioc])

        def done(r):
            self.info_lbl.configure(text="IOC added")
            cli_log(f"Created IOC: {itype} = {val} (source: {src})", "success")
            messagebox.showinfo("Done", "IOC created successfully.")

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total IOCs", "value": len(self.table._rows)}]
        export_report("Threat Intelligence", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Ranger & Rogues Page
# ═══════════════════════════════════════════════════════════════════════

class RangerPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Ranger & Rogues",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Network discovery — view Ranger findings and rogue devices.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load Ranger", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._ranger).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Load Rogues", height=34,
                      command=self._rogues).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Ranger: network discovery findings. "
                  "Rogues: unmanaged/rogue devices found on the network."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["hostname", "osType", "macAddress",
                                  "ipAddress", "manufacturer"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _ranger(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_ranger(max_items=500)

        def done(items):
            self.info_lbl.configure(text=f"{len(items)} Ranger findings")
            cli_log(f"Retrieved {len(items)} Ranger findings", "success")
            self.table.columns = ["hostname", "osType", "macAddress",
                                  "ipAddress", "manufacturer"]
            self.table.load(items)

        def fail(e):
            code = getattr(e, "status_code", 0)
            self.info_lbl.configure(text=f"Error ({code})" if code else f"Error: {e}")
            cli_log(f"Ranger endpoint error: {e}", "warning")

        run_async(self, do, done, fail)

    def _rogues(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_rogues(max_items=500)

        def done(items):
            self.info_lbl.configure(text=f"{len(items)} rogue devices")
            cli_log(f"Retrieved {len(items)} rogue devices", "success")
            self.table.columns = ["hostname", "osType", "macAddress",
                                  "ipAddress", "manufacturer"]
            self.table.load(items)

        def fail(e):
            code = getattr(e, "status_code", 0)
            self.info_lbl.configure(text=f"Error ({code})" if code else f"Error: {e}")
            cli_log(f"Rogues endpoint error: {e}", "warning")

        run_async(self, do, done, fail)

    def _export(self):
        stats = [{"label": "Total Devices", "value": len(self.table._rows)}]
        export_report("Ranger & Rogues", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Remote Scripts & Tasks Page
# ═══════════════════════════════════════════════════════════════════════

class RemoteScriptsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Remote Scripts & Tasks",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View RSO scripts and bulk task history.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Load Scripts", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._scripts).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Load Tasks", height=34,
                      command=self._tasks).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load Scripts: list available RSO scripts. "
                  "Load Tasks: show bulk task history (scheduled/completed)."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["scriptName", "osTypes", "scriptType",
                                  "createdAt", "id"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _scripts(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_scripts(max_items=500)

        def done(scripts):
            self.info_lbl.configure(text=f"{len(scripts)} scripts")
            cli_log(f"Retrieved {len(scripts)} remote scripts", "success")
            self.table.columns = ["scriptName", "osTypes", "scriptType",
                                  "createdAt", "id"]
            self.table.load(scripts)

        run_async(self, do, done)

    def _tasks(self):
        api = _pick_api(self.app)
        if not api:
            return

        def do():
            return api.get_tasks(max_items=200)

        def done(tasks):
            self.info_lbl.configure(text=f"{len(tasks)} tasks")
            cli_log(f"Retrieved {len(tasks)} bulk tasks", "success")
            self.table.columns = ["type", "status", "initiatedBy",
                                  "createdAt", "id"]
            self.table.load(tasks)

        run_async(self, do, done)

    def _export(self):
        stats = [{"label": "Total Items", "value": len(self.table._rows)}]
        export_report("Remote Scripts & Tasks", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Tags Page
# ═══════════════════════════════════════════════════════════════════════

class TagsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Tags",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="View firewall and network quarantine tags.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkLabel(btn, text="Type:", font=(UI_FONT, 13)).pack(
            side="left", padx=(0, 4))
        self.tag_type = ctk.CTkOptionMenu(btn,
                                          values=["firewall", "network-quarantine"],
                                          width=180, height=34)
        self.tag_type.pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Load Tags", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._load).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load tags by type: Firewall or Network Quarantine. "
                  "Requires a license that includes these features."
                  ).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.table = ResultTable(self,
                                 ["name", "type", "scope", "id"],
                                 height=300)
        self.table.grid(row=3, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return
        tt = self.tag_type.get()

        def do():
            return api.get_tags(tt, {"tenant": "true"})

        def done(tags):
            self.info_lbl.configure(text=f"{len(tags)} tags")
            self.table.load(tags)
            cli_log(f"Retrieved {len(tags)} tags ({tt})", "success")

        def fail(e):
            code = getattr(e, "status_code", 0)
            if code == 403:
                self.info_lbl.configure(text="No permission (403)")
                cli_log(f"Tags endpoint returned 403 — your token or console "
                        f"license may not include Firewall/NQ tags", "warning")
            else:
                self.info_lbl.configure(text=f"Error: {e}")

        run_async(self, do, done, fail)

    def _export(self):
        stats = [{"label": "Total Tags", "value": len(self.table._rows)}]
        export_report("Tags", self.table.columns, self.table._rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Raw API Page
# ═══════════════════════════════════════════════════════════════════════

class RawAPIPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Raw API",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Send raw GET/POST/PUT/DELETE requests to the S1 API.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(card, text="Method:", font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.method_var = ctk.StringVar(value="GET")
        ctk.CTkOptionMenu(card, values=["GET", "POST", "PUT", "DELETE"],
                          variable=self.method_var, width=100, height=32).grid(
            row=0, column=1, padx=6, pady=8, sticky="w")

        ctk.CTkLabel(card, text="Endpoint:", font=(UI_FONT, 13)).grid(
            row=1, column=0, padx=12, pady=8, sticky="w")
        self.endpoint_entry = ctk.CTkEntry(card,
                                           placeholder_text="/agents, /threats, etc.",
                                           height=32)
        self.endpoint_entry.grid(row=1, column=1, columnspan=2, padx=6,
                                 pady=8, sticky="ew")

        ctk.CTkLabel(card, text="JSON Body:", font=(UI_FONT, 13)).grid(
            row=2, column=0, padx=12, pady=8, sticky="nw")
        self.body_text = ctk.CTkTextbox(card, height=80, font=(MONO_FONT, 12))
        self.body_text.grid(row=2, column=1, columnspan=2, padx=6, pady=8, sticky="ew")

        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkButton(btn, text="Send Request", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._send).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Send a raw API request to the S1 console. "
                  "For GET, JSON body is used as query params. "
                  "For POST/PUT/DELETE, it is sent as the request body."
                  ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn, text="Export Report", height=34,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 6))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        self.log = _ConsoleProxy(self.app)

    def _send(self):
        api = _pick_api(self.app)
        if not api:
            return
        method = self.method_var.get()
        endpoint = self.endpoint_entry.get().strip()
        if not endpoint:
            messagebox.showwarning("Missing", "Enter an API endpoint.")
            return
        body_raw = self.body_text.get("1.0", "end").strip()
        body = None
        if body_raw:
            try:
                body = json.loads(body_raw)
            except json.JSONDecodeError as e:
                messagebox.showwarning("Invalid JSON", str(e))
                return

        self.log.clear()
        self.log.log(f"Sending {method} {endpoint}…")
        cli_log(f"Sending RAW {method} {endpoint}", "cmd")

        def do():
            if method == "GET":
                return api._get(endpoint, params=body)
            elif method == "POST":
                return api._post(endpoint, body=body)
            elif method == "PUT":
                return api._put(endpoint, body=body)
            elif method == "DELETE":
                return api._delete(endpoint, body=body)

        def done(result):
            self.info_lbl.configure(text="Response received")
            cli_log(f"RAW {method} {endpoint} — response received", "success")
            pretty = json.dumps(result, indent=2, default=str)
            for line in pretty.split("\n")[:200]:
                self.log.log(line)
            if len(pretty.split("\n")) > 200:
                self.log.log("… (truncated)")

        def fail(e):
            self.info_lbl.configure(text="Error")
            self.log.log(f"ERROR: {e}")

        run_async(self, do, done, fail)

    def _export(self):
        lines = self.log.get("1.0", "end").strip().split("\n")
        rows = [{"output": line} for line in lines if line.strip()]
        export_report("Raw API", ["output"], rows)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Purple AI Page
# ═══════════════════════════════════════════════════════════════════════

class PurpleAIPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Purple AI",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Natural language queries against SDL telemetry via Purple AI.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # input card
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="Question:", font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="nw")
        self.query_text = ctk.CTkTextbox(card, height=60, font=(UI_FONT, 13))
        self.query_text.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        opt_frame = ctk.CTkFrame(card, fg_color="transparent")
        opt_frame.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(opt_frame, text="View:", font=(UI_FONT, 12)).pack(
            side="left", padx=(0, 4))
        self.view_var = ctk.StringVar(value="EDR")
        ctk.CTkOptionMenu(opt_frame,
                          values=["EDR", "IDENTITY", "CLOUD", "NGFW", "DATA_LAKE"],
                          variable=self.view_var, width=130, height=30).pack(
            side="left", padx=(0, 12))

        ctk.CTkLabel(opt_frame, text="Hours:", font=(UI_FONT, 12)).pack(
            side="left", padx=(0, 4))
        self.hours_var = ctk.StringVar(value="24")
        ctk.CTkEntry(opt_frame, textvariable=self.hours_var,
                     width=50, height=30).pack(side="left", padx=(0, 12))

        # buttons
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        self._ask_btn = ctk.CTkButton(
            btn, text="🟣 Ask Purple AI", height=36,
            fg_color=BRAND, hover_color=BRAND_HOVER,
            font=(UI_FONT, 14, "bold"), command=self._ask)
        self._ask_btn.pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Ask a natural language question. Purple AI translates it to "
                  "a Power Query and returns a summary.\n\n"
                  "Domain: SDL telemetry (process, network, file events, indicators, "
                  "ingested logs). NOT for console entities like alerts, agents, sites."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn, text="Clear", height=36, fg_color=NEUTRAL,
                      command=self._clear).pack(side="left", padx=(0, 4))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        # results area
        result_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        result_frame.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 12))
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_rowconfigure(1, weight=1)

        # summary label
        self._summary_lbl = ctk.CTkLabel(result_frame, text="",
                                          font=(UI_FONT, 13),
                                          wraplength=800, justify="left",
                                          anchor="nw")
        self._summary_lbl.grid(row=0, column=0, padx=12, pady=(12, 4),
                               sticky="new")

        # response textbox (for message + power query)
        self._result_box = ctk.CTkTextbox(result_frame,
                                           font=(MONO_FONT, 12),
                                           fg_color=CONSOLE_BG,
                                           text_color=TEXT_MUTED)
        self._result_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._result_box.configure(state="disabled")

        # suggestions row
        self._suggestions_frame = ctk.CTkFrame(result_frame,
                                                fg_color="transparent")
        self._suggestions_frame.grid(row=2, column=0, padx=8, pady=(0, 8),
                                     sticky="ew")

    def _ask(self):
        api = _pick_api(self.app)
        if not api:
            return
        question = self.query_text.get("1.0", "end").strip()
        if not question:
            from tkinter import messagebox
            messagebox.showwarning("Missing", "Type a question.")
            return
        try:
            hours = int(self.hours_var.get())
        except ValueError:
            hours = 24

        view = self.view_var.get()
        self._ask_btn.configure(state="disabled", text="Thinking…")
        self.info_lbl.configure(text="Querying Purple AI…", text_color=WARN)
        cli_log(f"Purple AI: {question} (view={view}, hours={hours})", "cmd")

        def do():
            return api.purple_query(question, view_selector=view, hours=hours)

        def done(r):
            self._ask_btn.configure(state="normal", text="🟣 Ask Purple AI")
            state = r.get("state", "")
            self.info_lbl.configure(
                text=f"State: {state} | Type: {r.get('result_type', '')}",
                text_color=GREEN)
            # summary
            summary = r.get("summary") or ""
            self._summary_lbl.configure(text=summary if summary else "")
            # full message + power query
            self._result_box.configure(state="normal")
            self._result_box.delete("1.0", "end")
            msg = r.get("message") or ""
            if msg:
                self._result_box.insert("end", msg + "\n")
            pq = r.get("power_query")
            if pq:
                self._result_box.insert("end", f"\n{'─'*50}\n")
                self._result_box.insert("end", f"POWER QUERY:\n{pq}\n")
            vs = r.get("view_selector")
            if vs:
                self._result_box.insert("end", f"\nView: {vs}")
            tr = r.get("time_range")
            if tr and tr.get("start"):
                self._result_box.insert("end",
                    f"\nTime range: {tr['start']} → {tr['end']}")
            self._result_box.configure(state="disabled")
            # suggested questions
            for w in self._suggestions_frame.winfo_children():
                w.destroy()
            suggestions = r.get("suggested_questions") or []
            if suggestions:
                ctk.CTkLabel(self._suggestions_frame, text="Suggested:",
                             font=(UI_FONT, 11, "bold"),
                             text_color=TEXT_MUTED).pack(side="left", padx=(0, 6))
                for sq in suggestions[:3]:
                    ctk.CTkButton(
                        self._suggestions_frame, text=sq[:60],
                        height=26, font=(UI_FONT, 10),
                        fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                        command=lambda q=sq: self._use_suggestion(q)
                    ).pack(side="left", padx=2)
            cli_log(f"Purple AI response: {state}", "success")
            if pq:
                cli_log(f"  Power Query: {pq[:100]}…" if len(pq) > 100 else f"  Power Query: {pq}", "info")

        def fail(e):
            self._ask_btn.configure(state="normal", text="🟣 Ask Purple AI")
            self.info_lbl.configure(text=f"Error: {str(e)[:50]}",
                                    text_color=ACCENT)

        run_async(self, do, done, fail)

    def _use_suggestion(self, question):
        self.query_text.delete("1.0", "end")
        self.query_text.insert("1.0", question)
        self._ask()

    def _clear(self):
        self.query_text.delete("1.0", "end")
        self._summary_lbl.configure(text="")
        self._result_box.configure(state="normal")
        self._result_box.delete("1.0", "end")
        self._result_box.configure(state="disabled")
        for w in self._suggestions_frame.winfo_children():
            w.destroy()
        self.info_lbl.configure(text="")

    def on_show(self):
        self.app.set_active_console("source")


# ═══════════════════════════════════════════════════════════════════════
#  Unified Alerts Page
# ═══════════════════════════════════════════════════════════════════════

class UnifiedAlertsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self._alerts = []
        self._selected_ids = []
        self._cursor = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(self, text="Unified Alerts",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Modern multi-source alert triage via Unified Alert Management (GraphQL).",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # filters card
        filt = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        filt.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        filt.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(filt, text="Status:", font=(UI_FONT, 12)).grid(
            row=0, column=0, padx=(12, 4), pady=6, sticky="w")
        self.status_var = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(filt, values=["ALL", "NEW", "IN_PROGRESS", "RESOLVED"],
                          variable=self.status_var, width=120, height=30).grid(
            row=0, column=1, padx=4, pady=6, sticky="w")

        ctk.CTkLabel(filt, text="Severity:", font=(UI_FONT, 12)).grid(
            row=0, column=2, padx=(12, 4), pady=6, sticky="w")
        self.severity_var = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(filt, values=["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
                          variable=self.severity_var, width=120, height=30).grid(
            row=0, column=3, padx=4, pady=6, sticky="w")

        ctk.CTkLabel(filt, text="View:", font=(UI_FONT, 12)).grid(
            row=0, column=4, padx=(12, 4), pady=6, sticky="w")
        self.view_var = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(filt, values=["ALL", "ENDPOINT", "IDENTITY", "CLOUD",
                                         "STAR", "THIRD_PARTY"],
                          variable=self.view_var, width=130, height=30).grid(
            row=0, column=5, padx=(4, 12), pady=6, sticky="w")

        ctk.CTkLabel(filt, text="Page size:", font=(UI_FONT, 12)).grid(
            row=1, column=0, padx=(12, 4), pady=6, sticky="w")
        self.pagesize_var = ctk.StringVar(value="50")
        ctk.CTkEntry(filt, textvariable=self.pagesize_var,
                     width=60, height=30).grid(
            row=1, column=1, padx=4, pady=6, sticky="w")

        # facets row
        self._facets_frame = ctk.CTkFrame(filt, fg_color="transparent")
        self._facets_frame.grid(row=1, column=2, columnspan=4, padx=12, pady=6,
                                sticky="ew")

        # buttons
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        self._load_btn = ctk.CTkButton(
            btn, text="Load Alerts", height=36,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            font=(UI_FONT, 14, "bold"), command=self._load)
        self._load_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Next Page", height=36, fg_color=BRAND,
                      command=self._next_page).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn, text="Facets", height=36, fg_color=NEUTRAL,
                      command=self._load_facets).pack(side="left", padx=(0, 4))
        _help_btn(btn,
                  "Load: fetch alerts with filters. Next Page: paginate. "
                  "Facets: show severity/status/product distribution.\n\n"
                  "Detail: enter alert ID below to view notes, history, timeline."
                  ).pack(side="left", padx=(0, 8))
        self.info_lbl = ctk.CTkLabel(btn, text="", font=(UI_FONT, 12),
                                     text_color=TEXT_MUTED)
        self.info_lbl.pack(side="left", padx=8)

        # detail row
        det = ctk.CTkFrame(self, fg_color="transparent")
        det.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 4))
        ctk.CTkLabel(det, text="Alert ID:", font=(UI_FONT, 12)).pack(
            side="left", padx=(0, 4))
        self.alert_id_entry = ctk.CTkEntry(det, placeholder_text="for detail/notes/history",
                                            width=280, height=30)
        self.alert_id_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(det, text="Detail", height=30, width=70,
                      command=self._detail).pack(side="left", padx=(0, 4))
        ctk.CTkButton(det, text="Notes", height=30, width=70,
                      command=self._notes).pack(side="left", padx=(0, 4))
        ctk.CTkButton(det, text="History", height=30, width=70,
                      command=self._history).pack(side="left", padx=(0, 4))
        ctk.CTkButton(det, text="Timeline", height=30, width=70,
                      command=self._timeline).pack(side="left", padx=(0, 4))

        # triage buttons
        ctk.CTkButton(det, text="→ Resolve", height=30, width=80,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=lambda: self._triage("RESOLVED")).pack(
            side="left", padx=(12, 4))
        ctk.CTkButton(det, text="→ In Progress", height=30, width=100,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=lambda: self._triage("IN_PROGRESS")).pack(
            side="left", padx=(0, 4))
        ctk.CTkButton(det, text="Export CSV", height=30, width=90,
                      fg_color=NEUTRAL,
                      command=self._export_csv).pack(side="right")

        # results table
        self.table = ResultTable(self,
                                 ["name", "severity", "status", "detectedAt",
                                  "classification", "id"],
                                 height=300)
        self.table.grid(row=5, column=0, sticky="nsew", padx=20, pady=(4, 12))

    def _build_filters(self):
        filters = []
        st = self.status_var.get()
        if st != "ALL":
            filters.append({"fieldId": "status",
                            "stringEqual": {"value": st}})
        sv = self.severity_var.get()
        if sv != "ALL":
            filters.append({"fieldId": "severity",
                            "stringEqual": {"value": sv}})
        return filters

    def _load(self):
        api = _pick_api(self.app)
        if not api:
            return
        filters = self._build_filters()
        view = self.view_var.get()
        view_type = view if view != "ALL" else None
        try:
            page_size = int(self.pagesize_var.get())
        except ValueError:
            page_size = 50
        self._cursor = None
        self._load_btn.configure(state="disabled", text="Loading…")
        self.info_lbl.configure(text="Fetching…", text_color=WARN)
        cli_log(f"UAM: loading alerts (status={self.status_var.get()}, "
                f"severity={self.severity_var.get()}, view={view})", "cmd")

        def do():
            return api.uam_list_alerts(filters=filters, first=page_size,
                                       view_type=view_type)

        def done(result):
            self._load_btn.configure(state="normal", text="Load Alerts")
            edges = result.get("edges") or []
            total = result.get("totalCount", 0)
            pi = result.get("pageInfo") or {}
            self._cursor = pi.get("endCursor") if pi.get("hasNextPage") else None
            alerts = [e.get("node", {}) for e in edges]
            self._alerts = alerts
            self._selected_ids = [a.get("id", "") for a in alerts]
            # flatten detectionSource for display
            rows = []
            for a in alerts:
                ds = a.get("detectionSource") or {}
                rows.append({
                    "name": a.get("name", ""),
                    "severity": a.get("severity", ""),
                    "status": a.get("status", ""),
                    "detectedAt": (a.get("detectedAt") or "")[:19],
                    "classification": a.get("classification", ""),
                    "id": a.get("id", ""),
                })
            self.table.load(rows)
            more = " (more →)" if self._cursor else ""
            self.info_lbl.configure(
                text=f"{len(alerts)} alerts / {total} total{more}",
                text_color=GREEN)
            cli_log(f"UAM: {len(alerts)} alerts loaded ({total} total)", "success")

        def fail(e):
            self._load_btn.configure(state="normal", text="Load Alerts")
            self.info_lbl.configure(text=f"Error: {str(e)[:50]}",
                                    text_color=ACCENT)

        run_async(self, do, done, fail)

    def _next_page(self):
        if not self._cursor:
            cli_log("No more pages.", "warning")
            return
        api = _pick_api(self.app)
        if not api:
            return
        filters = self._build_filters()
        view = self.view_var.get()
        view_type = view if view != "ALL" else None
        try:
            page_size = int(self.pagesize_var.get())
        except ValueError:
            page_size = 50
        cursor = self._cursor
        cli_log("UAM: loading next page…", "cmd")

        def do():
            return api.uam_list_alerts(filters=filters, first=page_size,
                                       after=cursor, view_type=view_type)

        def done(result):
            edges = result.get("edges") or []
            pi = result.get("pageInfo") or {}
            self._cursor = pi.get("endCursor") if pi.get("hasNextPage") else None
            alerts = [e.get("node", {}) for e in edges]
            self._alerts.extend(alerts)
            self._selected_ids.extend([a.get("id", "") for a in alerts])
            for a in alerts:
                self.table.add_row({
                    "name": a.get("name", ""),
                    "severity": a.get("severity", ""),
                    "status": a.get("status", ""),
                    "detectedAt": (a.get("detectedAt") or "")[:19],
                    "classification": a.get("classification", ""),
                    "id": a.get("id", ""),
                })
            more = " (more →)" if self._cursor else " (end)"
            self.info_lbl.configure(
                text=f"{len(self._alerts)} total loaded{more}",
                text_color=GREEN)
            cli_log(f"UAM: +{len(alerts)} alerts (total {len(self._alerts)})", "success")

        run_async(self, do, done)

    def _load_facets(self):
        api = _pick_api(self.app)
        if not api:
            return
        filters = self._build_filters()
        cli_log("UAM: loading facets…", "cmd")

        def do():
            return api.uam_facets(["severity", "status", "detectionProduct"],
                                  filters=filters)

        def done(facets):
            for w in self._facets_frame.winfo_children():
                w.destroy()
            for f in facets:
                fid = f.get("fieldId", "")
                vals = f.get("values") or []
                parts = [f"{v.get('label') or v.get('value','?')}: {v.get('count',0)}"
                         for v in vals[:5]]
                text = f"{fid} — {', '.join(parts)}"
                ctk.CTkLabel(self._facets_frame, text=text,
                             font=(UI_FONT, 10), text_color=TEXT_MUTED).pack(
                    anchor="w")
                cli_log(f"  {text}", "info")
            cli_log("Facets loaded", "success")

        run_async(self, do, done)

    def _detail(self):
        api = _pick_api(self.app)
        aid = self.alert_id_entry.get().strip()
        if not api or not aid:
            return
        cli_log(f"UAM: fetching alert {aid}…", "cmd")

        def do():
            return api.uam_get_alert(aid)

        def done(alert):
            self.table.clear()
            # show all fields as key-value rows
            import json
            for k, v in alert.items():
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, default=str)[:80]
                self.table.add_row({"name": k, "severity": str(v)[:80],
                                    "status": "", "detectedAt": "",
                                    "classification": "", "id": ""})
            cli_log(f"Alert detail: {alert.get('name', '?')} — "
                    f"{alert.get('severity', '')} / {alert.get('status', '')}",
                    "success")

        run_async(self, do, done)

    def _notes(self):
        api = _pick_api(self.app)
        aid = self.alert_id_entry.get().strip()
        if not api or not aid:
            return
        cli_log(f"UAM: fetching notes for {aid}…", "cmd")

        def do():
            return api.uam_alert_notes(aid)

        def done(notes):
            self.table.columns = ["id", "text", "createdAt", "author",
                                  "type", "alertId"]
            self.table.clear()
            rows = []
            for n in notes:
                author = (n.get("author") or {}).get("fullName", "")
                rows.append({"id": n.get("id", ""), "text": n.get("text", ""),
                             "createdAt": n.get("createdAt", ""),
                             "author": author, "type": n.get("type", ""),
                             "alertId": n.get("alertId", "")})
            self.table.load(rows)
            self.info_lbl.configure(text=f"{len(notes)} notes")
            cli_log(f"UAM: {len(notes)} notes for alert {aid}", "success")

        run_async(self, do, done)

    def _history(self):
        api = _pick_api(self.app)
        aid = self.alert_id_entry.get().strip()
        if not api or not aid:
            return
        cli_log(f"UAM: fetching history for {aid}…", "cmd")

        def do():
            return api.uam_alert_history(aid)

        def done(result):
            edges = result.get("edges") or []
            events = [e.get("node", {}) for e in edges]
            self.table.columns = ["createdAt", "eventType", "eventText",
                                  "name", "severity", "status"]
            self.table.clear()
            rows = []
            for ev in events:
                rows.append({"createdAt": ev.get("createdAt", ""),
                             "eventType": ev.get("eventType", ""),
                             "eventText": ev.get("eventText", ""),
                             "name": "", "severity": "", "status": ""})
            self.table.load(rows)
            total = result.get("totalCount", len(events))
            self.info_lbl.configure(text=f"{len(events)} history events / {total} total")
            cli_log(f"UAM: {len(events)} history events for {aid}", "success")

        run_async(self, do, done)

    def _timeline(self):
        api = _pick_api(self.app)
        aid = self.alert_id_entry.get().strip()
        if not api or not aid:
            return
        cli_log(f"UAM: fetching timeline for {aid}…", "cmd")

        def do():
            return api.uam_alert_timeline(aid)

        def done(result):
            edges = result.get("edges") or []
            events = [e.get("node", {}) for e in edges]
            self.table.columns = ["createdAt", "eventType", "eventText",
                                  "name", "severity", "status"]
            self.table.clear()
            rows = []
            for ev in events:
                rows.append({"createdAt": ev.get("createdAt", ""),
                             "eventType": ev.get("eventType", ""),
                             "eventText": ev.get("eventText", ""),
                             "name": "", "severity": "", "status": ""})
            self.table.load(rows)
            total = result.get("totalCount", len(events))
            self.info_lbl.configure(text=f"{len(events)} timeline events / {total} total")
            cli_log(f"UAM: {len(events)} timeline events for {aid}", "success")

        run_async(self, do, done)

    def _triage(self, new_status):
        api = _pick_api(self.app)
        aid = self.alert_id_entry.get().strip()
        if not api:
            return
        ids = [aid] if aid else self._selected_ids
        if not ids:
            from tkinter import messagebox
            messagebox.showwarning("No alerts", "Load alerts or enter an alert ID.")
            return
        from tkinter import messagebox
        if not messagebox.askyesno("Confirm",
                                   f"Set {len(ids)} alert(s) to {new_status}?"):
            return
        # need account IDs for scope
        accounts = api.get_accounts()
        scope_ids = [a["id"] for a in accounts[:1]] if accounts else []
        cli_log(f"UAM: setting {len(ids)} alerts to {new_status}…", "cmd")

        def do():
            return api.uam_set_status(scope_ids, ids, new_status)

        def done(r):
            typename = r.get("__typename", "")
            if typename == "ActionsTriggered":
                acts = r.get("actions") or []
                success = sum(len(a.get("success", [])) for a in acts)
                cli_log(f"UAM: {success} alerts updated to {new_status}", "success")
                self.info_lbl.configure(
                    text=f"✓ {success} set to {new_status}", text_color=GREEN)
            elif typename == "TriggerActionsScheduled":
                cli_log(f"UAM: bulk action scheduled: {r.get('bulkActionTriggerId')}", "info")
                self.info_lbl.configure(text="Bulk action scheduled", text_color=WARN)
            else:
                errors = r.get("errors") or []
                msg = errors[0].get("errorMessage", "unknown") if errors else str(r)
                cli_log(f"UAM triage error: {msg}", "error")
                self.info_lbl.configure(text=f"Error: {msg[:40]}", text_color=ACCENT)

        run_async(self, do, done)

    def _export_csv(self):
        api = _pick_api(self.app)
        if not api:
            return
        filters = self._build_filters()
        view = self.view_var.get()
        cli_log("UAM: exporting alerts as CSV…", "cmd")

        def do():
            return api.uam_export_csv(filters=filters, view_type=view)

        def done(csv_data):
            if not csv_data:
                cli_log("No CSV data returned.", "warning")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                title="Save alerts CSV")
            if path:
                with open(path, "w") as f:
                    f.write(csv_data)
                cli_log(f"Alerts exported to {path}", "success")
                self.info_lbl.configure(text=f"Exported to {path}",
                                        text_color=GREEN)

        run_async(self, do, done)

    def on_show(self):
        self.app.set_active_console("source")
