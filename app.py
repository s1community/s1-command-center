"""
S1 Command Center GUI — Main window, sidebar, connections page.
Focused on: connect SOURCE + DESTINATION, then backup & restore.
"""
import customtkinter as ctk
import threading
import traceback
import os
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from typing import Optional, Callable

from s1_api import S1API, S1APIError
from config import ConfigManager

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SIDEBAR_BG = "#1a1a2e"
SIDEBAR_HOVER = "#16213e"
SIDEBAR_SEL = "#0f3460"
ACCENT = "#e94560"
GREEN = "#00b894"
WARN = "#fdcb6e"
CARD = "#2d2d44"


def _help_btn(parent, text):
    """Create a small ? button that prints help to the OUTPUT console."""
    import sys
    def _show():
        cli_log(text, "info")
    # Windows doesn't render high corner_radius well — use smaller radius
    cr = 13 if sys.platform == "darwin" else 6
    btn = ctk.CTkButton(parent, text="?", width=28, height=28,
                        font=("Segoe UI", 12, "bold"), fg_color="#444",
                        hover_color="#666", corner_radius=cr,
                        command=_show)
    return btn


# global ref filled by App.__init__; pages use cli_log() freely
_app_ref: Optional['App'] = None


def cli_log(msg: str, level: str = "info"):
    """Write a CLI-style message to the global output console."""
    if _app_ref:
        _app_ref.cli_log(msg, level)


def run_async(widget, fn, done=None, err=None):
    def _w():
        try:
            r = fn()
            if done:
                widget.after(0, lambda: done(r))
        except Exception as exc:
            tb = traceback.format_exc()
            e = exc  # capture before except scope clears it
            widget.after(0, lambda: cli_log(f"ERROR  {e}", "error"))
            if err:
                widget.after(0, lambda: err(e))
            else:
                widget.after(0, lambda: cli_log(tb, "error"))
    threading.Thread(target=_w, daemon=True).start()


class LogBox(ctk.CTkTextbox):
    def __init__(self, master, **kw):
        kw.setdefault("font", ("Consolas", 12))
        kw.setdefault("height", 200)
        super().__init__(master, **kw)
        self.configure(state="disabled")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.configure(state="normal")
        self.insert("end", f"[{ts}] {msg}\n")
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


class _ConsoleProxy:
    """Lightweight adapter so pages can use self.log.log() / .clear() / .get()
       but everything routes to the single global OUTPUT console."""

    def __init__(self, app):
        self._app = app

    def log(self, msg):
        self._app.cli_log(msg)

    def clear(self):
        self._app._clear_console()

    def get(self, *a, **kw):
        return self._app._console.get(*a, **kw)


class ConnectionsPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Console Connections",
                     font=("Segoe UI", 22, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Connect SOURCE (backup from) and DESTINATION (restore to).",
                     font=("Segoe UI", 13), text_color="gray").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 12))

        paste_row = ctk.CTkFrame(self, fg_color="transparent")
        paste_row.grid(row=2, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 4))
        ctk.CTkButton(paste_row, text="Paste from Clipboard", width=160, height=32,
                      fg_color="#2980b9", hover_color="#1f6da3",
                      command=self._paste_from_ticket).pack(side="left")
        _help_btn(paste_row,
                  "Copy a migration ticket block to your clipboard, "
                  "then click Paste from Ticket. Fills ALL pages.\n\n"
                  "Connections fields:\n"
                  "  Source console: <name>  |  URL: <source URL>  |  Token1: <token>\n"
                  "  Target Console: <name>  |  URL2: <dest URL>  |  Token2: <token>\n\n"
                  "Backup/Restore fields:\n"
                  "  Source Site: <site name>  →  Backup site filter\n"
                  "  Target Account: <name>  →  Restore account filter\n"
                  "  Mangle rename auto-filled from Source Console → Target Account\n\n"
                  "Other lines (Contact, Account ID, Notes) are ignored."
                  ).pack(side="left", padx=(4, 0))
        ctk.CTkButton(paste_row, text="Context List", width=120, height=32,
                      fg_color="#555", hover_color="#666",
                      command=self._refresh_list).pack(side="left", padx=(8, 0))
        ctk.CTkButton(paste_row, text="🔄 Reset All", width=110, height=32,
                      fg_color="#c0392b", hover_color="#e74c3c",
                      font=("Segoe UI", 12, "bold"),
                      command=self._reset_all).pack(side="left", padx=(8, 0))
        _help_btn(paste_row,
                  "Clear ALL fields across all pages — connections, backup "
                  "filters, restore data, output console — to start fresh."
                  ).pack(side="left", padx=(4, 0))
        self._paste_status = ctk.CTkLabel(paste_row, text="",
                                          font=("Segoe UI", 11),
                                          text_color="gray")
        self._paste_status.pack(side="left", padx=10)

        self.src_card = self._card("SOURCE", GREEN, 0)
        self.dst_card = self._card("DESTINATION", ACCENT, 1)

        ctk.CTkLabel(self, text="Saved Connections",
                     font=("Segoe UI", 15, "bold")).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 4))
        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color=CARD, corner_radius=12, height=160)
        self.list_frame.grid(
            row=5, column=0, columnspan=2, sticky="nsew", padx=20, pady=(0, 12))
        self.grid_rowconfigure(5, weight=1)
        self._refresh_list()

    def _card(self, role, color, col):
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        px = (20, 8) if col == 0 else (8, 20)
        card.grid(row=3, column=col, sticky="nsew", padx=px, pady=4)
        card.grid_columnconfigure(1, weight=1)

        title_fr = ctk.CTkFrame(card, fg_color="transparent")
        title_fr.grid(row=0, column=0, columnspan=2, sticky="w",
                      padx=12, pady=(12, 4))
        ctk.CTkLabel(title_fr, text=role, font=("Segoe UI", 15, "bold"),
                     text_color=color).pack(side="left")
        help_map = {
            "SOURCE": "Console to read/backup from. Enter a friendly name, "
                      "the console URL (full https://… or short name like "
                      "usea1-008), and an API token from the console.",
            "DESTINATION": "Console to write/restore to. Same fields — "
                           "name, URL, and API token.",
        }
        _help_btn(title_fr, help_map.get(role, "")).pack(
            side="left", padx=(6, 0))

        labels = ["Name:", "URL:", "API Token:"]
        entries = []
        for i, lbl in enumerate(labels):
            ctk.CTkLabel(card, text=lbl, font=("Segoe UI", 13)).grid(
                row=i+1, column=0, padx=12, pady=4, sticky="w")
            show = "•" if "Token" in lbl else None
            ph = {0: "my-console", 1: "https://… or short-name",
                  2: "Paste API token"}[i]
            e = ctk.CTkEntry(card, placeholder_text=ph, height=32, show=show)
            e.grid(row=i+1, column=1, padx=12, pady=4, sticky="ew")
            entries.append(e)

        status = ctk.CTkLabel(card, text="Not connected",
                              font=("Segoe UI", 11), text_color="gray")
        status.grid(row=5, column=0, columnspan=2, padx=12, pady=(0, 8),
                    sticky="w")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=4, column=0, columnspan=2, padx=12, pady=6, sticky="ew")

        role_lower = role.lower()
        ctk.CTkButton(btns, text="Test", width=60, height=32,
                      command=lambda: self._test(
                          entries[1], entries[2], status)).pack(
            side="left", padx=(0, 2))
        _help_btn(btns,
                  "Verify the URL and API token are valid "
                  "by calling the /my-user endpoint.").pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Save & Connect", width=130, height=32,
                      fg_color=color,
                      command=lambda: self._save(
                          entries, role_lower, status)).pack(
            side="left", padx=(0, 2))
        _help_btn(btns,
                  f"Save credentials to disk and activate this "
                  f"console as the {role_lower}.").pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Delete", width=60, height=32,
                      fg_color="#555",
                      command=lambda: self._delete(
                          entries[0], status)).pack(side="right")

        return {"entries": entries, "status": status}

    def _test(self, url_e, tok_e, status):
        url, tok = url_e.get().strip(), tok_e.get().strip()
        if not url or not tok:
            messagebox.showwarning("Missing", "Fill URL and token.")
            return
        if not url.startswith("http"):
            url = f"https://{url}.sentinelone.net"
        status.configure(text="Testing…", text_color=WARN)

        def do():
            return S1API(url, tok).get_my_user()

        def ok(u):
            status.configure(text=f"OK — {u.get('fullName', '?')}",
                             text_color=GREEN)

        def fail(e):
            status.configure(text=f"Failed: {e}", text_color=ACCENT)

        run_async(self, do, ok, fail)

    def _save(self, entries, role, status):
        n = entries[0].get().strip()
        u = entries[1].get().strip()
        t = entries[2].get().strip()
        if not all([n, u, t]):
            messagebox.showwarning("Missing", "Fill all fields.")
            return
        self.app.cfg.upsert(n, u, t, role)
        self.app.cfg.set_role(n, role)
        # remove old entries that have no active role
        self.app.cfg.contexts = [
            c for c in self.app.cfg.contexts if c.role in ("source", "destination")]
        self.app.cfg.save()
        self.app.connect(role)
        status.configure(text="Saved & connected ✓", text_color=GREEN)
        self._refresh_list()

    def _delete(self, name_e, status):
        n = name_e.get().strip()
        if not n:
            return
        self.app.cfg.remove(n)
        status.configure(text="Deleted", text_color="gray")
        self._refresh_list()

    def _refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.app.cfg.contexts:
            ctk.CTkLabel(self.list_frame, text="No saved connections.",
                         text_color="gray").pack(pady=16)
            return
        # header
        hdr = ctk.CTkFrame(self.list_frame, fg_color="#1a1a2e",
                            corner_radius=6)
        hdr.pack(fill="x", pady=(4, 2), padx=4)
        for col, w in [("Role", 60), ("Name", 160), ("URL", 0)]:
            kw = {"text": col, "font": ("Segoe UI", 11, "bold"),
                  "text_color": "#888"}
            if w:
                kw["width"] = w
            ctk.CTkLabel(hdr, **kw).pack(side="left", padx=8, pady=4)
        # rows
        for ctx in self.app.cfg.contexts:
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", pady=1, padx=4)
            if ctx.role == "source":
                badge, c = "SRC", GREEN
            elif ctx.role == "destination":
                badge, c = "DST", ACCENT
            else:
                badge, c = "—", "gray"
            ctk.CTkLabel(row, text=badge, font=("Segoe UI", 12, "bold"),
                         text_color=c, width=60).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=ctx.name,
                         font=("Segoe UI", 13, "bold"),
                         text_color="white", width=160).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=ctx.display_url,
                         font=("Segoe UI", 12),
                         text_color="gray").pack(side="left", padx=8)
            token_hint = ctx.api_token[:8] + "…" if len(ctx.api_token) > 8 else "—"
            ctk.CTkLabel(row, text=f"token: {token_hint}",
                         font=("Consolas", 10),
                         text_color="#555").pack(side="right", padx=8)

    def _paste_from_ticket(self):
        """Parse clipboard text and fill SOURCE + DESTINATION + Backup/Restore fields."""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            cli_log("Clipboard is empty or unavailable.", "error")
            self._paste_status.configure(text="Clipboard empty", text_color=ACCENT)
            return

        fields = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()

        src_name = fields.get("source console", "")
        src_url  = fields.get("url", "")
        src_tok  = fields.get("token1", "")
        dst_name = fields.get("target console", "")
        dst_url  = fields.get("url2", "")
        dst_tok  = fields.get("token2", "")
        # use Source Account for backup/restore (not Source Console)
        src_acct = fields.get("source account", "") or fields.get("source console", "")
        src_site = fields.get("source site", "")
        tgt_acct = fields.get("target account", "")

        filled = 0
        if src_name or src_url or src_tok:
            self._fill_entries(self.src_card["entries"], src_name, src_url, src_tok)
            filled += 1
            cli_log(f"Pasted SOURCE: {src_name} / {src_url}", "info")
        if dst_name or dst_url or dst_tok:
            self._fill_entries(self.dst_card["entries"], dst_name, dst_url, dst_tok)
            filled += 1
            cli_log(f"Pasted DESTINATION: {dst_name} / {dst_url}", "info")

        # Fill Backup page filters
        backup_page = self.app.pages.get("Backup Source")
        if backup_page:
            if src_acct:
                self._set_entry(backup_page.acct_filter, src_acct)
            if src_site and src_site.lower() != "all sites":
                self._set_entry(backup_page.site_filter, src_site)
            cli_log(f"Pasted Backup filters: account={src_acct}, site={src_site}", "info")

        # Fill Restore page filters + mangle
        restore_page = self.app.pages.get("Restore to Dest")
        if restore_page:
            if tgt_acct:
                self._set_entry(restore_page.restore_acct, tgt_acct)
            if src_site and src_site.lower() != "all sites":
                self._set_entry(restore_page.restore_site, src_site)
            # Mangle rename: source → target
            if src_acct:
                mangle_src = src_acct
                if src_site and src_site.lower() != "all sites":
                    mangle_src = f"{src_acct}/{src_site}"
                self._set_entry(restore_page.mangle_src, mangle_src)
            if tgt_acct:
                mangle_dst = tgt_acct
                if src_site and src_site.lower() != "all sites":
                    mangle_dst = f"{tgt_acct}/{src_site}"
                self._set_entry(restore_page.mangle_dst, mangle_dst)
            cli_log(f"Pasted Restore filters: account={tgt_acct}, "
                    f"mangle={src_acct}→{tgt_acct}", "info")

        if filled or src_acct or tgt_acct:
            self._paste_status.configure(text="Ticket pasted to all pages",
                                         text_color=GREEN)
            cli_log("Ticket data pasted into connection + backup + restore fields.", "success")
        else:
            self._paste_status.configure(text="No fields found in clipboard",
                                         text_color=ACCENT)
            cli_log("Could not parse any connection fields from clipboard.", "warning")

    @staticmethod
    def _fill_entries(entries, name, url, token):
        """Clear and fill [name, url, token] entry widgets."""
        for entry, val in zip(entries, [name, url, token]):
            if val:
                entry.delete(0, "end")
                entry.insert(0, val)

    @staticmethod
    def _set_entry(entry, val):
        """Clear and set a single entry widget."""
        if val:
            entry.delete(0, "end")
            entry.insert(0, val)

    def _reset_all(self):
        """Clear ALL fields across all pages to start a fresh migration."""
        if not messagebox.askyesno(
                "Reset All",
                "This will clear ALL fields, connections, backup data, "
                "restore data, and the output console.\n\n"
                "Are you sure you want to start fresh?"):
            return

        # clear connection entries
        for card in (self.src_card, self.dst_card):
            for e in card["entries"]:
                e.delete(0, "end")
            card["status"].configure(text="Not connected", text_color="gray")

        # disconnect APIs
        self.app.source_api = None
        self.app.dest_api = None
        self.app.src_lbl.configure(text="not connected", text_color="gray")
        self.app.dst_lbl.configure(text="not connected", text_color="gray")
        self.app._last_backup_path = None

        # clear backup page
        bp = self.app.pages.get("Backup Source")
        if bp:
            for e in [bp.acct_filter, bp.site_filter, bp.group_filter]:
                e.delete(0, "end")
            bp.ptable.clear()
            bp.progress.set(0)
            bp._timer_lbl.configure(text="")
            bp._status_lbl.configure(text="")
            bp._operation_log = []

        # clear restore page
        rp = self.app.pages.get("Restore to Dest")
        if rp:
            rp.file_entry.delete(0, "end")
            rp.backup_data = None
            rp.info_lbl.configure(text="")
            for e in [rp.restore_acct, rp.restore_site, rp.restore_group]:
                e.delete(0, "end")
            rp.mangle_src.delete(0, "end")
            rp.mangle_dst.delete(0, "end")
            rp.mangle_status.configure(text="")
            rp.ptable.clear()
            rp.progress.set(0)
            rp._timer_lbl.configure(text="")
            rp._status_lbl.configure(text="")
            rp._operation_log = []
            rp._report_nodes = []
            rp._report_meta = {}

        # clear output console
        self.app._clear_console()

        self._paste_status.configure(
            text="All cleared — ready for new migration", text_color=GREEN)
        cli_log("All fields reset — ready for a new migration.", "success")

    def on_show(self):
        self._refresh_list()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("S1 Command Center")
        w, h = 1200, 780
        sx = self.winfo_screenwidth()
        sy = self.winfo_screenheight()
        x = (sx - w) // 2
        y = (sy - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(900, 600)
        icon_path = os.path.join(os.path.dirname(__file__), "s1cc.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        global _app_ref
        _app_ref = self

        self.cfg = ConfigManager()
        self.source_api: Optional[S1API] = None
        self.dest_api: Optional[S1API] = None
        self.pages = {}
        self._current = None
        self._btns = []
        self._console_visible = True

        self._build()
        self._startup_banner()
        self.connect("source")
        self.connect("destination")

    def _build(self):
        # sidebar
        sb = ctk.CTkFrame(self, width=250, fg_color=SIDEBAR_BG,
                          corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=14, pady=(14, 4))
        ctk.CTkLabel(logo, text="S1 Command Center",
                     font=("Segoe UI", 22, "bold"),
                     text_color="white").pack(anchor="w")
        self._src_frame = ctk.CTkFrame(logo, fg_color="#0d3b2e", corner_radius=6)
        self._src_frame.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(self._src_frame, text="SRC", font=("Segoe UI", 9, "bold"),
                     text_color=GREEN, width=30).pack(side="left", padx=(6, 4))
        self.src_lbl = ctk.CTkLabel(self._src_frame, text="not connected",
                                    font=("Segoe UI", 10),
                                    text_color="gray")
        self.src_lbl.pack(side="left", padx=(0, 6))

        self._dst_frame = ctk.CTkFrame(logo, fg_color="#3b0d1e", corner_radius=6)
        self._dst_frame.pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(self._dst_frame, text="DST", font=("Segoe UI", 9, "bold"),
                     text_color=ACCENT, width=30).pack(side="left", padx=(6, 4))
        self.dst_lbl = ctk.CTkLabel(self._dst_frame, text="not connected",
                                    font=("Segoe UI", 10),
                                    text_color="gray")
        self.dst_lbl.pack(side="left", padx=(0, 6))

        self._active_lbl = ctk.CTkLabel(logo, text="",
                                         font=("Segoe UI", 10, "bold"),
                                         text_color="#888")
        self._active_lbl.pack(fill="x", pady=(4, 0))

        # import pages lazily here to avoid circular issues
        from pages import BackupPage, RestorePage, AgentMigrationPage
        from pages_extra import (
            AccountsSitesPage, AgentsPage, ThreatsPage, UsersRolesPage,
            ActivitiesPage, DeepVisibilityPage, ExclusionsBlocklistPage,
            STARRulesPage, ApplicationsCVEsPage, ThreatIntelPage,
            RangerPage, RemoteScriptsPage, TagsPage, RawAPIPage,
        )

        nav_migration = [
            ("Connections", ConnectionsPage),
            ("Backup Source", BackupPage),
            ("Restore to Dest", RestorePage),
            ("Agent Migration", AgentMigrationPage),
        ]
        nav_ops = [
            ("Accounts & Sites", AccountsSitesPage),
            ("Agents", AgentsPage),
            ("Threats", ThreatsPage),
            ("Exclusions & Block", ExclusionsBlocklistPage),
            ("STAR Rules", STARRulesPage),
            ("Users & Roles", UsersRolesPage),
            ("Activities", ActivitiesPage),
            ("Deep Visibility", DeepVisibilityPage),
            ("Apps & CVEs", ApplicationsCVEsPage),
            ("Threat Intel", ThreatIntelPage),
            ("Ranger & Rogues", RangerPage),
            ("Remote Scripts", RemoteScriptsPage),
            ("Tags", TagsPage),
            ("Raw API", RawAPIPage),
        ]
        nav = nav_migration + nav_ops

        nav_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent", scrollbar_button_color="#333",
            scrollbar_button_hover_color="#555")
        nav_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        for i, (label, cls) in enumerate(nav):
            if i == len(nav_migration):
                sep = ctk.CTkFrame(nav_scroll, height=1, fg_color="#444")
                sep.pack(fill="x", padx=14, pady=6)
                ctk.CTkLabel(nav_scroll, text="OPERATIONS",
                             font=("Segoe UI", 9, "bold"),
                             text_color="#666").pack(
                    anchor="w", padx=14, pady=(0, 2))
            b = ctk.CTkButton(nav_scroll, text=label, anchor="w", height=34,
                              font=("Segoe UI", 12), fg_color="transparent",
                              text_color="white", hover_color=SIDEBAR_HOVER,
                              corner_radius=8,
                              command=lambda l=label: self._show(l))
            b.pack(fill="x", padx=10, pady=1)
            self._btns.append((label, b))

        # credit at bottom of sidebar
        ctk.CTkLabel(sb, text="Made by Ran Jacobi",
                     font=("Segoe UI", 9), text_color="#555").pack(
            side="bottom", pady=(0, 8))
        ctk.CTkLabel(sb, text="v1.0.1",
                     font=("Segoe UI", 9), text_color="#444").pack(
            side="bottom", pady=(0, 2))

        # right side: content + console
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        # main area
        self.content = ctk.CTkFrame(right, fg_color="transparent")
        self.content.pack(fill="both", expand=True)

        # ── CLI Output Console ──────────────────────────────────────
        self._console_frame = ctk.CTkFrame(right, fg_color="#0d0d1a",
                                           corner_radius=8)
        self._console_frame.pack(fill="both", side="bottom", expand=True,
                                 padx=6, pady=(4, 6))

        console_header = ctk.CTkFrame(self._console_frame,
                                      fg_color="#151528", height=30,
                                      corner_radius=0)
        console_header.pack(fill="x")
        ctk.CTkLabel(console_header, text="⬤  OUTPUT",
                     font=("Segoe UI", 10, "bold"),
                     text_color="#00b894").pack(side="left", padx=10)
        ctk.CTkButton(console_header, text="Clear", width=50, height=22,
                      font=("Segoe UI", 10), fg_color="#333",
                      hover_color="#555",
                      command=self._clear_console).pack(
            side="right", padx=4, pady=2)
        ctk.CTkButton(console_header, text="Toggle", width=50, height=22,
                      font=("Segoe UI", 10), fg_color="#333",
                      hover_color="#555",
                      command=self._toggle_console).pack(
            side="right", padx=4, pady=2)

        self._console = ctk.CTkTextbox(
            self._console_frame, font=("Consolas", 11), height=220,
            fg_color="#0d0d1a", text_color="#cccccc",
            corner_radius=0)
        self._console.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self._console.configure(state="disabled")

        # status bar
        self.status = ctk.CTkLabel(right, text="Ready", anchor="w",
                                   font=("Segoe UI", 11), height=24)
        self.status.pack(side="bottom", fill="x", padx=10)

        # create pages
        for label, cls in nav:
            p = cls(self.content, self)
            self.pages[label] = p

        self._show("Connections")

    def _show(self, label):
        if self._current:
            self._current.pack_forget()
        p = self.pages[label]
        p.pack(fill="both", expand=True)
        self._current = p
        for lbl, btn in self._btns:
            btn.configure(fg_color=SIDEBAR_SEL if lbl == label
                          else "transparent")
        if hasattr(p, "on_show"):
            p.on_show()
        elif hasattr(p, "_console_var"):
            pass  # page will set it via on_show
        else:
            self.set_active_console("")

    def connect(self, role):
        ctx = self.cfg.get_by_role(role)
        if not ctx:
            return
        api = S1API(ctx.url, ctx.api_token)
        if role == "source":
            self.source_api = api
            self.src_lbl.configure(
                text=f"{ctx.name}\n{ctx.display_url}", text_color=GREEN)
        else:
            self.dest_api = api
            self.dst_lbl.configure(
                text=f"{ctx.name}\n{ctx.display_url}", text_color=ACCENT)

    def set_active_console(self, role: str):
        """Highlight which console (source/destination) is active for current operation."""
        if role == "source":
            self._src_frame.configure(fg_color="#0f5e3f")
            self._dst_frame.configure(fg_color="#3b0d1e")
            self._active_lbl.configure(
                text="▶ ACTIVE: SOURCE", text_color=GREEN)
        elif role == "destination":
            self._src_frame.configure(fg_color="#0d3b2e")
            self._dst_frame.configure(fg_color="#5e0f2a")
            self._active_lbl.configure(
                text="▶ ACTIVE: DESTINATION", text_color=ACCENT)
        else:
            self._src_frame.configure(fg_color="#0d3b2e")
            self._dst_frame.configure(fg_color="#3b0d1e")
            self._active_lbl.configure(text="", text_color="#888")

    def set_status(self, msg):
        self.status.configure(text=msg)

    # ── CLI-style output console ──────────────────────────────────

    def cli_log(self, msg: str, level: str = "info"):
        """Append a CLI-style line to the global output console."""
        ts = datetime.now().strftime("%H:%M:%S")
        prefix_map = {
            "info":    f"[{ts}]",
            "success": f"[{ts}] ✓",
            "warning": f"[{ts}] ⚠",
            "error":   f"[{ts}] ✗",
            "cmd":     f"[{ts}] >",
            "banner":  "",
        }
        prefix = prefix_map.get(level, f"[{ts}]")
        line = f"{prefix} {msg}\n" if prefix else f"{msg}\n"
        self._console.configure(state="normal")
        self._console.insert("end", line)
        self._console.see("end")
        self._console.configure(state="disabled")

    def _clear_console(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")

    def _toggle_console(self):
        if self._console_visible:
            self._console.pack_forget()
            self._console_visible = False
        else:
            self._console.pack(fill="both", expand=True, padx=2, pady=(0, 2))
            self._console_visible = True

    def _startup_banner(self):
        self.cli_log("═" * 60, "banner")
        self.cli_log("  S1 Command Center GUI", "banner")
        self.cli_log("  SentinelOne console management tool", "banner")
        self.cli_log("  Made by Ran Jacobi", "banner")
        self.cli_log("  This software is provided AS IS, free of charge.", "banner")
        self.cli_log("═" * 60, "banner")
        self.cli_log("Application started", "success")
        src = self.cfg.get_by_role("source")
        dst = self.cfg.get_by_role("destination")
        if src:
            self.cli_log(f"Auto-connecting SOURCE: {src.name} ({src.display_url})", "info")
        else:
            self.cli_log("No SOURCE console configured", "warning")
        if dst:
            self.cli_log(f"Auto-connecting DESTINATION: {dst.name} ({dst.display_url})", "info")
        else:
            self.cli_log("No DESTINATION console configured", "warning")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
