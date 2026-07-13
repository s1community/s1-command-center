"""
S1 Command Center GUI — Main window, sidebar, connections page.
Focused on: connect SOURCE + DESTINATION, then backup & restore.
"""
import customtkinter as ctk
from PIL import Image
import threading
import traceback
import os
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from typing import Optional, Callable

from s1_api import S1API, S1APIError
from config import (ConfigManager, ProfileManager, CONFIG_DIR, APP_VERSION,
                    SettingsManager)
from migtools import AuditLog
import theme

# Apply the brand design system (dark mode + violet primary) before any
# widget is created.
theme.apply()

# ── Design tokens, re-exported for pages.py / pages_extra.py / jira_page.py ──
# These names are imported by the page modules, so the whole app re-themes
# from theme.py.
APP_BG        = theme.APP_BG
SIDEBAR_BG    = theme.SIDEBAR_BG
SIDEBAR_HOVER = theme.SIDEBAR_HOVER
SIDEBAR_SEL   = theme.SIDEBAR_SEL
ACCENT        = theme.ACCENT
ACCENT_HOVER  = theme.ACCENT_HOVER
GREEN         = theme.GREEN
GREEN_HOVER   = theme.GREEN_HOVER
WARN          = theme.WARN
WARN_HOVER    = theme.WARN_HOVER
INFO          = theme.INFO
CARD          = theme.CARD
CARD_ELEVATED = theme.CARD_ELEVATED
INPUT_BG      = theme.INPUT_BG
BORDER        = theme.BORDER
MIG_PANEL     = theme.MIG_PANEL
MIG_BORDER    = theme.MIG_BORDER
BRAND         = theme.BRAND
BRAND_HOVER   = theme.BRAND_HOVER
BRAND_LIGHT   = theme.BRAND_LIGHT
NEUTRAL       = theme.NEUTRAL
NEUTRAL_HOVER = theme.NEUTRAL_HOVER
GHOST         = theme.GHOST
GHOST_HOVER   = theme.GHOST_HOVER
CONSOLE_BG    = theme.CONSOLE_BG
TEXT          = theme.TEXT
TEXT_MUTED    = theme.TEXT_MUTED
TEXT_FAINT    = theme.TEXT_FAINT
UI_FONT       = theme.UI_FONT
MONO_FONT     = theme.MONO_FONT


class _ToolTip:
    """Lightweight hover/click tooltip — shows help text in a small popup next
    to the widget instead of dumping it into the OUTPUT console."""
    def __init__(self, widget, text, wraplength=340):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self._tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() - 4
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tw.wm_geometry(f"+{x}+{y}")
        border = tk.Frame(tw, background=theme.tkcolor(BORDER))
        border.pack()
        tk.Label(border, text=self.text, justify="left",
                 wraplength=self.wraplength,
                 background=theme.tkcolor(CARD_ELEVATED),
                 foreground=theme.tkcolor(TEXT), font=(UI_FONT, 11),
                 padx=10, pady=8).pack(padx=1, pady=1)

    def _hide(self, _e=None):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _toggle(self, _e=None):
        # Click also toggles, for trackpad users who miss the hover.
        self._hide() if self._tip is not None else self._show()


def _help_btn(parent, text):
    """Create a small ? button that reveals its help in a hover/click tooltip
    (no more OUTPUT-console spam on every click)."""
    import sys
    # Windows doesn't render high corner_radius well — use smaller radius
    cr = 13 if sys.platform == "darwin" else 6
    # Soft pill: light-grey in light mode (NEUTRAL is a dark slate there, which
    # looked heavy/ugly for a tiny "?"); unchanged dark styling in dark mode.
    btn = ctk.CTkButton(parent, text="?", width=28, height=28,
                        font=(UI_FONT, 12, "bold"),
                        fg_color=GHOST, hover_color=GHOST_HOVER,
                        text_color=TEXT_MUTED, border_width=1,
                        border_color=BORDER, corner_radius=cr)
    tip = _ToolTip(btn, text)
    btn.configure(command=tip._toggle)
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
        kw.setdefault("font", (MONO_FONT, 12))
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
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Connect SOURCE (backup from) and DESTINATION (restore to).",
                     font=(UI_FONT, 13), text_color="gray").grid(
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
                      font=(UI_FONT, 12, "bold"),
                      command=self._reset_all).pack(side="left", padx=(8, 0))
        _help_btn(paste_row,
                  "Clear ALL fields across all pages — backup filters, restore "
                  "data, output console — AND permanently delete every saved "
                  "connection, to start fresh."
                  ).pack(side="left", padx=(4, 0))
        self._paste_status = ctk.CTkLabel(paste_row, text="",
                                          font=(UI_FONT, 11),
                                          text_color="gray")
        self._paste_status.pack(side="left", padx=10)

        self.src_card = self._card("SOURCE", GREEN, 0)
        self.dst_card = self._card("DESTINATION", ACCENT, 1)

        # ── Saved Connections ──────────────────────────────────────────
        saved_hdr = ctk.CTkFrame(self, fg_color="transparent")
        saved_hdr.grid(row=4, column=0, columnspan=2, sticky="ew",
                       padx=20, pady=(16, 4))
        ctk.CTkLabel(saved_hdr, text="Saved Connections",
                     font=(UI_FONT, 15, "bold")).pack(side="left")
        ctk.CTkButton(saved_hdr, text="🗑  Delete All", width=110, height=28,
                      fg_color="#c0392b", hover_color="#e74c3c",
                      font=(UI_FONT, 12, "bold"),
                      command=self._delete_all_connections).pack(
            side="right")
        _help_btn(saved_hdr,
                  "Remove every saved connection from disk and disconnect "
                  "both SOURCE and DESTINATION. Cannot be undone."
                  ).pack(side="right", padx=(0, 6))
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
        ctk.CTkLabel(title_fr, text=role, font=(UI_FONT, 15, "bold"),
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
            ctk.CTkLabel(card, text=lbl, font=(UI_FONT, 13)).grid(
                row=i+1, column=0, padx=12, pady=4, sticky="w")
            show = "•" if "Token" in lbl else None
            ph = {0: "my-console", 1: "https://… or short-name",
                  2: "Paste API token"}[i]
            e = ctk.CTkEntry(card, placeholder_text=ph, height=32, show=show)
            e.grid(row=i+1, column=1, padx=12, pady=4, sticky="ew")
            entries.append(e)

        # Ignore-SSL-errors checkbox row (above buttons)
        ssl_var = tk.BooleanVar(
            value=bool(self.app.settings.get("default_ignore_ssl", False)))
        ssl_row = ctk.CTkFrame(card, fg_color="transparent")
        ssl_row.grid(row=4, column=0, columnspan=2, padx=12, pady=(2, 0),
                     sticky="w")
        ctk.CTkCheckBox(ssl_row, text="Ignore SSL errors",
                        variable=ssl_var, onvalue=True, offvalue=False,
                        font=(UI_FONT, 12),
                        checkbox_width=18, checkbox_height=18).pack(side="left")
        _help_btn(ssl_row,
                  "Skip TLS certificate verification when calling this "
                  "console. Useful for consoles behind a corporate "
                  "MITM proxy or with self-signed certs. Leave OFF unless "
                  "you know you need it — disabling verification weakens "
                  "transport security."
                  ).pack(side="left", padx=(6, 0))

        status = ctk.CTkLabel(card, text="Not connected",
                              font=(UI_FONT, 11), text_color="gray")
        status.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 8),
                    sticky="w")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=5, column=0, columnspan=2, padx=12, pady=6, sticky="ew")

        role_lower = role.lower()
        ctk.CTkButton(btns, text="Test", width=60, height=32,
                      command=lambda: self._test(
                          entries[1], entries[2], status, ssl_var)).pack(
            side="left", padx=(0, 2))
        _help_btn(btns,
                  "Verify the URL and API token are valid "
                  "by calling the /my-user endpoint.").pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Save & Connect", width=130, height=32,
                      fg_color=color,
                      command=lambda: self._save(
                          entries, role_lower, status, ssl_var)).pack(
            side="left", padx=(0, 2))
        _help_btn(btns,
                  f"Save credentials to disk and activate this "
                  f"console as the {role_lower}.").pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Delete", width=60, height=32,
                      fg_color="#555",
                      command=lambda: self._delete(
                          entries[0], status)).pack(side="right")

        return {"entries": entries, "status": status, "ssl_var": ssl_var}

    def _test(self, url_e, tok_e, status, ssl_var=None):
        url, tok = url_e.get().strip(), tok_e.get().strip()
        if not url or not tok:
            messagebox.showwarning("Missing", "Fill URL and token.")
            return
        if not url.startswith("http"):
            url = f"https://{url}.sentinelone.net"
        verify = not (ssl_var.get() if ssl_var is not None else False)
        status.configure(text="Testing…", text_color=WARN)

        def do():
            return S1API(url, tok, verify_ssl=verify).get_my_user()

        def ok(u):
            status.configure(text=f"OK — {u.get('fullName', '?')}",
                             text_color=GREEN)

        def fail(e):
            short = str(e)[:60]
            status.configure(text=f"Failed: {short}", text_color=ACCENT)

        run_async(self, do, ok, fail)

    def _save(self, entries, role, status, ssl_var=None):
        n = entries[0].get().strip()
        u = entries[1].get().strip()
        t = entries[2].get().strip()
        if not all([n, u, t]):
            messagebox.showwarning("Missing", "Fill all fields.")
            return
        ignore_ssl = bool(ssl_var.get()) if ssl_var is not None else False
        ctx = self.app.cfg.upsert(n, u, t, role,
                                  ignore_ssl_errors=ignore_ssl)
        # Identify by the normalized URL (upsert may have prefixed the scheme),
        # so saving doesn't collide with another context that happens to share
        # the same friendly name.
        self.app.cfg.set_role(ctx.url, role)
        # Keep previously-active contexts in the list (their role gets demoted
        # to "" by set_role) so the user can switch back to them later via the
        # per-row "Use as SRC/DST" buttons.
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

    def _delete_all_connections(self):
        """Wipe all saved connections from disk and disconnect both APIs."""
        if not self.app.cfg.contexts:
            cli_log("No saved connections to delete.", "info")
            return
        count = len(self.app.cfg.contexts)
        if not messagebox.askyesno(
                "Delete All Connections",
                f"Permanently delete all {count} saved connection"
                f"{'s' if count != 1 else ''}?\n\n"
                "Both SOURCE and DESTINATION will be disconnected.\n"
                "This cannot be undone."):
            return
        self.app.cfg.contexts = []
        self.app.cfg.save()
        # disconnect APIs + clear sidebar status
        self.app.source_api = None
        self.app.dest_api = None
        self.app.src_lbl.configure(text="not connected", text_color="gray")
        self.app.dst_lbl.configure(text="not connected", text_color="gray")
        # clear connection card entries + statuses
        for card in (self.src_card, self.dst_card):
            for e in card["entries"]:
                e.delete(0, "end")
            if "ssl_var" in card:
                card["ssl_var"].set(False)
            card["status"].configure(text="Not connected", text_color="gray")
        self._refresh_list()
        cli_log(f"Deleted all {count} saved connection"
                f"{'s' if count != 1 else ''}.", "success")

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
            kw = {"text": col, "font": (UI_FONT, 11, "bold"),
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
            ctk.CTkLabel(row, text=badge, font=(UI_FONT, 12, "bold"),
                         text_color=c, width=60).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=ctx.name,
                         font=(UI_FONT, 13, "bold"),
                         text_color="white", width=160).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=ctx.display_url,
                         font=(UI_FONT, 12),
                         text_color="gray").pack(side="left", padx=8)
            # right-side actions: delete + role toggles
            ctk.CTkButton(row, text="✕", width=26, height=24,
                          fg_color="#555", hover_color="#c0392b",
                          font=(UI_FONT, 11, "bold"),
                          command=lambda u=ctx.url: self._delete_by_url(u)
                          ).pack(side="right", padx=(4, 8))
            ctk.CTkButton(row, text="Use as DST", width=86, height=24,
                          font=(UI_FONT, 10, "bold"),
                          fg_color=ACCENT if ctx.role != "destination" else "#3b0d1e",
                          hover_color="#c0392b",
                          state="disabled" if ctx.role == "destination" else "normal",
                          command=lambda u=ctx.url: self._activate_as(u, "destination")
                          ).pack(side="right", padx=2)
            ctk.CTkButton(row, text="Use as SRC", width=86, height=24,
                          font=(UI_FONT, 10, "bold"),
                          fg_color=GREEN if ctx.role != "source" else "#0d3b2e",
                          hover_color="#00875a",
                          state="disabled" if ctx.role == "source" else "normal",
                          command=lambda u=ctx.url: self._activate_as(u, "source")
                          ).pack(side="right", padx=2)
            token_hint = ctx.api_token[:8] + "…" if len(ctx.api_token) > 8 else "—"
            ctk.CTkLabel(row, text=f"token: {token_hint}",
                         font=(MONO_FONT, 10),
                         text_color="#555").pack(side="right", padx=8)

    def _activate_as(self, url: str, role: str):
        """Promote a saved context (identified by URL) to the given role."""
        ctx = self.app.cfg.get_by_url(url)
        if not ctx:
            cli_log(f"Connection for {url} not found.", "error")
            return
        self.app.cfg.set_role(ctx.url, role)
        # mirror into the SRC/DST card so the UI matches the active context
        card = self.src_card if role == "source" else self.dst_card
        self._fill_entries(card["entries"], ctx.name, ctx.url, ctx.api_token)
        if "ssl_var" in card:
            card["ssl_var"].set(bool(getattr(ctx, "ignore_ssl_errors", False)))
        card["status"].configure(text="Active ✓", text_color=GREEN)
        self.app.connect(role)
        cli_log(f"Activated {ctx.name} ({ctx.display_url}) as {role.upper()}",
                "success")
        self._refresh_list()

    def _delete_by_url(self, url: str):
        """Delete a single saved connection by URL (with confirmation)."""
        ctx = self.app.cfg.get_by_url(url)
        if not ctx:
            return
        label = f"{ctx.name} ({ctx.display_url})"
        if not messagebox.askyesno(
                "Delete Connection",
                f"Delete saved connection '{label}'?"):
            return
        self.app.cfg.remove(ctx.url)
        # if we just deleted the active SRC/DST, disconnect that side too
        if ctx.role == "source":
            self.app.source_api = None
            self.app.src_lbl.configure(text="not connected", text_color="gray")
        elif ctx.role == "destination":
            self.app.dest_api = None
            self.app.dst_lbl.configure(text="not connected", text_color="gray")
        cli_log(f"Deleted connection '{label}'.", "info")
        self._refresh_list()

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

        # Fill Migration Validation page (source + destination entries)
        val_page = self.app.pages.get("Migration Validation")
        if val_page:
            if src_acct:
                self._set_entry(val_page._src_acct, src_acct)
            if src_site and src_site.lower() != "all sites":
                self._set_entry(val_page._src_site, src_site)
            if tgt_acct:
                self._set_entry(val_page._dst_acct, tgt_acct)
            if src_site and src_site.lower() != "all sites":
                self._set_entry(val_page._dst_site, src_site)
            if hasattr(val_page, "on_show"):
                try:
                    val_page.on_show()
                except Exception:
                    pass
            cli_log(f"Pasted Validation filters: source={src_acct}/{src_site}, "
                    f"dest={tgt_acct}/{src_site}", "info")

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
                "This will clear ALL fields, backup data, restore data, and the "
                "output console, and PERMANENTLY delete every saved connection "
                "(source & destination).\n\n"
                "Are you sure you want to start fresh?"):
            return

        # clear connection entries
        for card in (self.src_card, self.dst_card):
            for e in card["entries"]:
                e.delete(0, "end")
            if "ssl_var" in card:
                card["ssl_var"].set(False)
            card["status"].configure(text="Not connected", text_color="gray")

        # wipe ALL saved connections from disk (+ keyring) for a clean slate
        self.app.cfg.clear()
        self._refresh_list()

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


class SettingsPage(ctk.CTkFrame):
    """App preferences — persisted to settings.json via App.settings."""

    _SCALES = {
        "Auto (fit window)": 0.0,
        "90%": 0.9, "100%": 1.0, "110%": 1.1, "125%": 1.25, "150%": 1.5,
    }

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        s = self.app.settings

        ctk.CTkLabel(self, text="Settings",
                     font=(UI_FONT, 22, "bold")).pack(
            anchor="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(
            self,
            text="Preferences save automatically and persist across restarts "
                 "and app updates.",
            font=(UI_FONT, 13), text_color=TEXT_MUTED).pack(
            anchor="w", padx=20, pady=(0, 12))

        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._wrap = wrap

        # ── Appearance & Display ──
        card = self._card("Appearance & Display")
        self._add_row(card, "Theme",
                      "Light, dark, or follow the system setting. Switches live.")
        self._theme_var = ctk.StringVar(value=s.get("appearance_mode", "Dark"))
        ctk.CTkOptionMenu(card, values=["System", "Dark", "Light"],
                          variable=self._theme_var, width=180,
                          command=self._on_theme).grid(
            row=self._row, column=1, sticky="e", padx=16, pady=6)
        self._add_row(card, "UI scale",
                      "Size of all text and controls. 'Auto' fits the window.")
        self._scale_var = ctk.StringVar(
            value=self._scale_to_label(s.get("ui_scale", 0.0)))
        ctk.CTkOptionMenu(card, values=list(self._SCALES.keys()),
                          variable=self._scale_var, width=180,
                          command=self._on_scale).grid(
            row=self._row, column=1, sticky="e", padx=16, pady=6)
        self._switch(card, "Start in fullscreen",
                     "Open filling the screen. Toggle anytime with ⌘⇧F, "
                     "exit with Esc.",
                     bool(s.get("start_fullscreen")), self._on_start_fullscreen)

        # ── General ──
        card = self._card("General")
        self._switch(card, "Open OUTPUT console on launch",
                     "Start with the log / console drawer already open.",
                     bool(s.get("console_open_on_start")),
                     self._on_console_start)

        # ── Restore ──
        card = self._card("Restore")
        self._switch(card, "Snapshot destination before restore (default)",
                     "Pre-tick 'Snapshot first' on the Restore page so a bad "
                     "restore can be rolled back.",
                     bool(s.get("restore_snapshot_default", True)),
                     self._on_snapshot_default)

        # ── Security & Storage ──
        card = self._card("Security & Storage")
        self._switch(card, "Store API tokens in OS keychain",
                     "Use the macOS Keychain / Windows Credential Manager for "
                     "tokens instead of the local file. macOS prompts for "
                     "keychain access on each token read/write.",
                     bool(s.get("enable_keyring")), self._on_keyring)
        self._switch(card, "Ignore SSL errors for new connections",
                     "Pre-tick 'Ignore SSL errors' when adding a new console "
                     "(useful for lab / self-signed environments).",
                     bool(s.get("default_ignore_ssl")), self._on_default_ssl)

        # Save button. Settings already auto-save on every change; this writes
        # the file on demand and confirms it, for peace of mind.
        save_row = ctk.CTkFrame(wrap, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(10, 2))
        self._save_status = ctk.CTkLabel(save_row, text="", font=(UI_FONT, 11),
                                         text_color=GREEN)
        self._save_status.pack(side="right", padx=(8, 6))
        ctk.CTkButton(save_row, text="💾  Save Settings", height=32, width=150,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      font=(UI_FONT, 12, "bold"),
                      command=self._save_settings).pack(side="right")

        ctk.CTkLabel(
            wrap,
            text="Stored in ~/.s1-command-center/settings.json (outside the "
                 "app), so your settings are kept across every app update.",
            font=(UI_FONT, 10), text_color=TEXT_FAINT, justify="left",
            wraplength=560).pack(anchor="w", padx=16, pady=(6, 4))

    # ── layout helpers ──
    def _card(self, title):
        c = ctk.CTkFrame(self._wrap, fg_color=CARD, corner_radius=12)
        c.pack(fill="x", padx=14, pady=6)
        c.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=title, font=(UI_FONT, 14, "bold"),
                     text_color=ACCENT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        self._row = 0
        return c

    def _add_row(self, card, title, desc):
        self._row += 1
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.grid(row=self._row, column=0, sticky="w", padx=16, pady=6)
        ctk.CTkLabel(box, text=title, font=(UI_FONT, 13, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(box, text=desc, font=(UI_FONT, 11), wraplength=560,
                     justify="left", text_color=TEXT_FAINT).pack(anchor="w")

    def _switch(self, card, title, desc, initial, command):
        self._add_row(card, title, desc)
        var = ctk.BooleanVar(value=initial)
        ctk.CTkSwitch(card, text="", variable=var, width=48,
                      command=lambda: command(var)).grid(
            row=self._row, column=1, sticky="e", padx=16, pady=6)
        return var

    def _scale_to_label(self, val):
        for k, v in self._SCALES.items():
            if abs(v - (val or 0.0)) < 1e-3:
                return k
        return "Auto (fit window)"

    # ── handlers ──
    def _on_scale(self, label):
        val = self._SCALES.get(label, 0.0)
        self.app.settings.set("ui_scale", val)
        self.app.apply_ui_scale(val)

    def _on_theme(self, mode):
        ctk.set_appearance_mode(mode)   # CustomTkinter widgets switch live
        theme.refresh_tk()              # repaint tracked raw-tk widgets
        self.app.settings.set("appearance_mode", mode)

    def _on_start_fullscreen(self, var):
        self.app.settings.set("start_fullscreen", bool(var.get()))

    def _on_console_start(self, var):
        self.app.settings.set("console_open_on_start", bool(var.get()))

    def _on_snapshot_default(self, var):
        self.app.settings.set("restore_snapshot_default", bool(var.get()))

    def _on_default_ssl(self, var):
        self.app.settings.set("default_ignore_ssl", bool(var.get()))

    def _on_keyring(self, var):
        on = bool(var.get())
        self.app.settings.set("enable_keyring", on)
        if on:
            os.environ["S1CC_ENABLE_KEYRING"] = "1"
        else:
            os.environ.pop("S1CC_ENABLE_KEYRING", None)
        try:
            self.app.cfg.save()   # migrate tokens to/from the OS keychain
            cli_log("OS keychain storage "
                    + ("enabled — tokens moved to the keychain." if on
                       else "disabled — tokens kept in the local file."),
                    "info")
        except Exception as exc:
            cli_log(f"Keychain toggle failed: {exc}", "error")

    def _save_settings(self):
        self.app.settings.save()
        self._save_status.configure(text="Saved ✓")
        self.after(2000, lambda: self._save_status.configure(text=""))
        cli_log("Settings saved.", "success")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("S1 Command Center")
        # Size the window to a sensible fraction of the actual screen instead
        # of a fixed 1200×780, so it's well-proportioned on laptops and large
        # external displays alike.
        sx, sy = self.winfo_screenwidth(), self.winfo_screenheight()
        self._win_w = max(1120, min(1600, int(sx * 0.80)))
        self._win_h = max(720, min(1000, int(sy * 0.84)))
        self.minsize(1000, 640)
        self._center_on_screen()
        # Re-assert centering after the WM has finished placing the window
        # (some platforms ignore the first geometry call on launch).
        self.after(50, self._center_on_screen)

        # Auto UI scaling: grow every widget proportionally as the window gets
        # larger (and back down when smaller) so big/full-screen displays don't
        # look sparse and tiny. Debounced + bucketed to avoid thrash.
        self.settings = SettingsManager()
        if self.settings.get("enable_keyring"):
            os.environ["S1CC_ENABLE_KEYRING"] = "1"
        _saved_scale = self.settings.get("ui_scale", 0.0) or 0.0
        self._ui_scale = _saved_scale if _saved_scale else 1.0
        self._auto_scale = not _saved_scale   # 0.0 → follow window size
        self._scale_after = None
        if _saved_scale:
            ctk.set_widget_scaling(_saved_scale)
        self.bind("<Configure>", self._on_resize)

        # Manual zoom override (Cmd/Ctrl +/-/0) — once used, it pins the scale.
        for seq in ("<Command-equal>", "<Command-plus>", "<Control-equal>",
                    "<Control-plus>"):
            self.bind(seq, lambda e: self._zoom(0.1))
        for seq in ("<Command-minus>", "<Control-minus>"):
            self.bind(seq, lambda e: self._zoom(-0.1))
        for seq in ("<Command-0>", "<Control-0>"):
            self.bind(seq, lambda e: self._zoom_reset())

        # Fullscreen — bound to ⌘⇧F (reliable on macOS) plus F11 / ⌘⌃F for
        # platforms where those aren't intercepted by the OS; Esc exits. (Tk on
        # macOS doesn't hook the native green-button fullscreen.)
        self._is_fullscreen = False
        for seq in ("<F11>", "<Command-Control-f>", "<Control-Command-f>",
                    "<Command-Shift-F>", "<Control-Shift-F>"):
            self.bind(seq, self._toggle_fullscreen)
        self.bind("<Escape>", self._exit_fullscreen)
        icon_path = os.path.join(os.path.dirname(__file__), "s1cc.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        global _app_ref
        _app_ref = self

        self.cfg = ConfigManager()
        self.profiles = ProfileManager()
        self.audit = AuditLog(os.path.join(CONFIG_DIR, "audit.jsonl"))
        self.source_api: Optional[S1API] = None
        self.dest_api: Optional[S1API] = None
        self.pages = {}
        self._current = None
        self._btns = []
        self._console_visible = False   # OUTPUT drawer starts collapsed
        self._busy = False              # a backup/restore is in progress
        self._saved_btn_states = {}

        self._build()
        self._startup_banner()
        self.connect("source")
        self.connect("destination")

        # Apply the saved "start in fullscreen" preference once the window is up.
        if self.settings.get("start_fullscreen"):
            self.after(250, self._toggle_fullscreen)
        if self.settings.get("console_open_on_start"):
            self.after(300, self.show_console)

    def _center_on_screen(self):
        """Place the window centered on whichever screen Tk reports."""
        self.update_idletasks()
        w, h = self._win_w, self._win_h
        sx = self.winfo_screenwidth()
        sy = self.winfo_screenheight()
        x = max(0, (sx - w) // 2)
        y = max(0, (sy - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_resize(self, event):
        """Debounce window resizes, then rescale the UI to match the new size."""
        if event.widget is not self:
            return
        if self._scale_after:
            self.after_cancel(self._scale_after)
        self._scale_after = self.after(160, self._apply_auto_scale)

    def _apply_auto_scale(self):
        """Pick a widget-scaling factor from the current window width so the UI
        fills large windows without looking cramped, and stays compact on small
        ones. Bucketed to 0.05 steps; only re-applied when it actually changes."""
        self._scale_after = None
        if not self._auto_scale:        # user took manual control via zoom
            return
        if not hasattr(self, "status"):  # _build() not finished yet
            return
        w = self.winfo_width()
        if w < 50:                      # window not realized yet
            return
        # Reference design width ~1200 → 1.0; grow gently up to 1.35.
        factor = max(1.0, min(1.35, w / 1240))
        factor = round(factor * 20) / 20
        if abs(factor - self._ui_scale) >= 0.05:
            self._ui_scale = factor
            ctk.set_widget_scaling(factor)

    def _zoom(self, delta):
        """Manual zoom — pins the scale (disables auto) and steps it."""
        self._auto_scale = False
        self._ui_scale = max(0.7, min(2.0, round((self._ui_scale + delta) * 20) / 20))
        ctk.set_widget_scaling(self._ui_scale)
        self.set_status(f"UI zoom: {int(self._ui_scale * 100)}%  "
                        f"(⌘0 to reset / auto-fit)")

    def _zoom_reset(self):
        """Back to automatic, window-size-driven scaling."""
        self._auto_scale = True
        self._ui_scale = 0.0            # force the next auto pass to re-apply
        self._apply_auto_scale()
        self.set_status("UI zoom: auto-fit to window size")

    def apply_ui_scale(self, val):
        """Settings hook: apply a fixed UI scale (val>0) or return to
        window-fit auto scaling (val==0). Mirrors the ⌘± / ⌘0 zoom controls."""
        if val:
            self._auto_scale = False
            self._ui_scale = val
            ctk.set_widget_scaling(val)
            self.set_status(f"UI scale: {int(val * 100)}%")
        else:
            self._auto_scale = True
            self._ui_scale = 0.0
            self._apply_auto_scale()
            self.set_status("UI scale: auto-fit to window")

    def _toggle_fullscreen(self, event=None):
        """Enter/leave true fullscreen. macOS Tk doesn't hook the native
        green-button fullscreen, so this is the reliable path."""
        self._is_fullscreen = not self._is_fullscreen
        try:
            self.attributes("-fullscreen", self._is_fullscreen)
        except Exception:
            # Fallback for any platform without -fullscreen: fill the screen.
            if self._is_fullscreen:
                self.geometry(f"{self.winfo_screenwidth()}x"
                              f"{self.winfo_screenheight()}+0+0")
        if hasattr(self, "status"):
            self.set_status("Fullscreen on (Esc or ⌘⇧F to exit)"
                            if self._is_fullscreen else "Fullscreen off")
        return "break"

    def _exit_fullscreen(self, event=None):
        """Esc leaves fullscreen — but only when we're actually in it, so
        dialogs keep their own Escape handling the rest of the time."""
        if not self._is_fullscreen:
            return None
        self._is_fullscreen = False
        try:
            self.attributes("-fullscreen", False)
        except Exception:
            pass
        if hasattr(self, "status"):
            self.set_status("Fullscreen off")
        return "break"

    def _build(self):
        # ── Sidebar ──────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=258, fg_color=SIDEBAR_BG,
                          corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # Brand lockup: app-icon picture logo + wordmark
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(20, 14))
        self._logo_img = None
        logo_path = os.path.join(os.path.dirname(__file__), "s1cc.ico")
        if os.path.exists(logo_path):
            try:
                self._logo_img = ctk.CTkImage(Image.open(logo_path),
                                              size=(40, 40))
            except Exception:
                self._logo_img = None
        if self._logo_img is not None:
            ctk.CTkLabel(brand, image=self._logo_img, text="").pack(side="left")
        else:
            # Fallback to the original violet "S1" tile if the image is missing.
            mark = ctk.CTkFrame(brand, width=40, height=40, fg_color=BRAND,
                                corner_radius=theme.RADIUS_MD)
            mark.pack(side="left")
            mark.pack_propagate(False)
            ctk.CTkLabel(mark, text="S1", font=(UI_FONT, 17, "bold"),
                         text_color="#FFFFFF").pack(expand=True)
        wm = ctk.CTkFrame(brand, fg_color="transparent")
        wm.pack(side="left", padx=(11, 0))
        ctk.CTkLabel(wm, text="Command Center", font=(UI_FONT, 16, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(wm, text="SentinelOne Console Suite",
                     font=(UI_FONT, 10), text_color=TEXT_FAINT).pack(anchor="w")

        # Connection status card (SRC / DST)
        conn = ctk.CTkFrame(sb, fg_color=CARD, corner_radius=theme.RADIUS_MD)
        conn.pack(fill="x", padx=14, pady=(0, 10))

        self._src_frame = ctk.CTkFrame(conn, fg_color="transparent",
                                       corner_radius=theme.RADIUS_SM)
        self._src_frame.pack(fill="x", padx=8, pady=(8, 3))
        ctk.CTkLabel(self._src_frame, text="●", font=(UI_FONT, 12, "bold"),
                     text_color=GREEN, width=14).pack(side="left", padx=(6, 2))
        ctk.CTkLabel(self._src_frame, text="SRC", font=(UI_FONT, 10, "bold"),
                     text_color=GREEN, width=30).pack(side="left")
        self.src_lbl = ctk.CTkLabel(self._src_frame, text="not connected",
                                    font=(UI_FONT, 10), text_color=TEXT_FAINT,
                                    anchor="w", justify="left")
        self.src_lbl.pack(side="left", padx=(2, 6), fill="x", expand=True)

        self._dst_frame = ctk.CTkFrame(conn, fg_color="transparent",
                                       corner_radius=theme.RADIUS_SM)
        self._dst_frame.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(self._dst_frame, text="●", font=(UI_FONT, 12, "bold"),
                     text_color=ACCENT, width=14).pack(side="left", padx=(6, 2))
        ctk.CTkLabel(self._dst_frame, text="DST", font=(UI_FONT, 10, "bold"),
                     text_color=ACCENT, width=30).pack(side="left")
        self.dst_lbl = ctk.CTkLabel(self._dst_frame, text="not connected",
                                    font=(UI_FONT, 10), text_color=TEXT_FAINT,
                                    anchor="w", justify="left")
        self.dst_lbl.pack(side="left", padx=(2, 6), fill="x", expand=True)

        self._active_lbl = ctk.CTkLabel(conn, text="", font=(UI_FONT, 10, "bold"),
                                        text_color=TEXT_FAINT, anchor="w")
        self._active_lbl.pack(fill="x", padx=14, pady=(0, 6))

        # import pages lazily here to avoid circular issues
        from pages import (BackupPage, RestorePage, AgentMigrationPage,
                           ValidationPage, MigrationRunbookPage)
        from pages_extra import (
            AccountsSitesPage, AgentsPage, ThreatsPage, UsersRolesPage,
            ActivitiesPage, DeepVisibilityPage, ExclusionsBlocklistPage,
            STARRulesPage, ApplicationsCVEsPage, ThreatIntelPage,
            RangerPage, RemoteScriptsPage, TagsPage, RawAPIPage,
            PurpleAIPage, UnifiedAlertsPage,
        )
        # Optional private extension module is loaded only if the user has
        # an admin marker file AND the module is actually present on disk.
        # Public builds ship without the module, so this branch is a no-op
        # for end users.
        admin_flag = os.path.join(os.path.expanduser("~"),
                                  ".s1-command-center", "admin.flag")
        is_admin = os.path.exists(admin_flag)

        nav_migration = [
            ("Connections", ConnectionsPage),
            ("Migration Runbook", MigrationRunbookPage),
            ("Backup Source", BackupPage),
            ("Restore to Dest", RestorePage),
            ("Agent Migration", AgentMigrationPage),
            ("Migration Validation", ValidationPage),
        ]
        if is_admin:
            try:
                from jira_page import JiraPage  # noqa: F401  (optional)
                nav_migration.insert(0, ("PSO Tickets", JiraPage))
            except ImportError:
                pass
        # Operations pages are grouped into collapsible categories so the
        # MIGRATION workflow stays the visual focus instead of competing with
        # a flat list of 16 buttons.
        nav_ops_groups = [
            ("Inventory", [
                ("Accounts & Sites", AccountsSitesPage),
                ("Agents", AgentsPage),
                ("Apps & CVEs", ApplicationsCVEsPage),
                ("Ranger & Rogues", RangerPage),
                ("Tags", TagsPage),
            ]),
            ("Detection & Response", [
                ("Threats", ThreatsPage),
                ("Unified Alerts", UnifiedAlertsPage),
                ("STAR Rules", STARRulesPage),
                ("Threat Intel", ThreatIntelPage),
                ("Deep Visibility", DeepVisibilityPage),
                ("Purple AI", PurpleAIPage),
            ]),
            ("Policy & Control", [
                ("Exclusions & Block", ExclusionsBlocklistPage),
                ("Remote Scripts", RemoteScriptsPage),
            ]),
            ("Admin", [
                ("Users & Roles", UsersRolesPage),
                ("Activities", ActivitiesPage),
            ]),
            ("Advanced", [
                ("Raw API", RawAPIPage),
            ]),
        ]
        nav_ops = [item for _grp, items in nav_ops_groups for item in items]
        nav = nav_migration + nav_ops

        nav_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent", scrollbar_button_color=NEUTRAL,
            scrollbar_button_hover_color=NEUTRAL_HOVER)
        nav_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        def _eyebrow(parent, text, color, top, pad):
            ctk.CTkLabel(parent, text=text, font=(UI_FONT, 10, "bold"),
                         text_color=color, anchor="w").pack(
                anchor="w", padx=pad, pady=(top, 4))

        def _nav_item(parent, label, hover):
            # Row = thin active-indicator bar + button, so the selected page
            # gets a violet accent strip down its left edge.
            row = ctk.CTkFrame(parent, fg_color="transparent", height=36)
            row.pack(fill="x", padx=6, pady=1)
            row.pack_propagate(False)
            bar = ctk.CTkFrame(row, width=3, fg_color="transparent",
                               corner_radius=2)
            bar.pack(side="left", fill="y", padx=(2, 0), pady=5)
            btn = ctk.CTkButton(
                row, text=label, anchor="w", height=34, font=(UI_FONT, 12),
                fg_color="transparent", text_color=TEXT_MUTED,
                hover_color=hover, corner_radius=theme.RADIUS_SM,
                command=lambda l=label: self._show(l))
            btn.pack(side="left", fill="x", expand=True, padx=(6, 4))
            self._btns.append((label, btn, bar))

        # Collapsible operations categories. self._nav_groups maps each group
        # title → {expand, collapse, labels} so _show() can auto-open the
        # group that owns the page being shown.
        self._nav_groups = {}

        def _nav_group(parent, title, items):
            collapsed = {"v": True}
            content = ctk.CTkFrame(parent, fg_color="transparent")
            header = ctk.CTkButton(
                parent, text=f"▸  {title}", anchor="w", height=30,
                font=(UI_FONT, 11, "bold"), fg_color="transparent",
                text_color=TEXT_MUTED, hover_color=SIDEBAR_HOVER,
                corner_radius=theme.RADIUS_SM)

            def _set(open_):
                collapsed["v"] = not open_
                if open_:
                    content.pack(after=header, fill="x", padx=0, pady=(0, 2))
                    header.configure(text=f"▾  {title}")
                else:
                    content.pack_forget()
                    header.configure(text=f"▸  {title}")

            header.configure(command=lambda: _set(collapsed["v"]))
            header.pack(fill="x", padx=8, pady=(2, 0))
            for label, _cls in items:
                _nav_item(content, label, SIDEBAR_HOVER)
            self._nav_groups[title] = {
                "expand": lambda: _set(True),
                "labels": [lbl for lbl, _c in items],
            }

        # MIGRATION workflow lives inside a distinct violet-tinted panel so it
        # reads as the primary workflow, set apart from the OPERATIONS tools.
        mig_box = ctk.CTkFrame(nav_scroll, fg_color=MIG_PANEL,
                               corner_radius=theme.RADIUS_MD,
                               border_width=1, border_color=MIG_BORDER)
        mig_box.pack(fill="x", padx=8, pady=(2, 8))
        _eyebrow(mig_box, "MIGRATION", BRAND_LIGHT, 8, 14)
        for label, cls in nav_migration:
            _nav_item(mig_box, label, SIDEBAR_HOVER)
        ctk.CTkFrame(mig_box, fg_color="transparent", height=4).pack()

        _eyebrow(nav_scroll, "OPERATIONS", TEXT_FAINT, 6, 18)
        for title, items in nav_ops_groups:
            _nav_group(nav_scroll, title, items)

        # Footer: settings gear + version + brand credit
        footer = ctk.CTkFrame(sb, fg_color="transparent")
        footer.pack(side="bottom", fill="x", pady=(4, 10))
        ver_row = ctk.CTkFrame(footer, fg_color="transparent")
        ver_row.pack()
        gear = ctk.CTkButton(
            ver_row, text="⚙  Settings", height=28,
            font=(UI_FONT, 11, "bold"), fg_color=GHOST,
            hover_color=GHOST_HOVER, text_color=TEXT_MUTED,
            border_width=1, border_color=BORDER,
            corner_radius=theme.RADIUS_SM,
            command=lambda: self._show("Settings"))
        gear.pack(side="left", padx=(0, 8))
        _ToolTip(gear, "Appearance & display preferences")
        ctk.CTkLabel(ver_row, text=f"v{APP_VERSION}", font=(UI_FONT, 10, "bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(footer, text="Built by Ran Jacobi · Professional Services",
                     font=(UI_FONT, 9), text_color=TEXT_FAINT).pack(pady=(3, 0))

        # ── center column: page content fills it; OUTPUT lives in a drawer
        #    that slides up from a slim always-visible status bar ──────────
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self.content = ctk.CTkFrame(right, fg_color="transparent")
        self.content.pack(side="top", fill="both", expand=True)

        # Status bar (always visible): live status + latest log line + toggle.
        bar = ctk.CTkFrame(right, fg_color=CARD_ELEVATED, height=30,
                           corner_radius=0)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.status = ctk.CTkLabel(bar, text="Ready", anchor="w",
                                   font=(UI_FONT, 11), text_color=TEXT_MUTED)
        self.status.pack(side="left", padx=12)
        self._drawer_btn = ctk.CTkButton(
            bar, text="▴  OUTPUT", width=104, height=22,
            font=(UI_FONT, 10, "bold"), fg_color=GHOST,
            hover_color=GHOST_HOVER, text_color=GREEN,
            border_width=1, border_color=BORDER,
            corner_radius=theme.RADIUS_SM, command=self._toggle_console)
        self._drawer_btn._busy_exempt = True   # log toggle usable during runs
        self._drawer_btn.pack(side="right", padx=8, pady=4)
        self._log_preview = ctk.CTkLabel(bar, text="", anchor="e",
                                         font=(MONO_FONT, 10),
                                         text_color=TEXT_FAINT)
        self._log_preview.pack(side="right", padx=8, fill="x", expand=True)

        # The drawer itself — built once, packed above the bar only when open.
        self._drawer_h = 260
        self._drawer = ctk.CTkFrame(right, height=self._drawer_h,
                                    fg_color=CONSOLE_BG, corner_radius=0,
                                    border_width=1, border_color=BORDER)
        self._drawer.pack_propagate(False)

        # Drag handle on the drawer's top edge → resize its height.
        d_grip = ctk.CTkFrame(self._drawer, height=5, fg_color=BORDER,
                              cursor="sb_v_double_arrow")
        d_grip.pack(side="top", fill="x")
        d_grip.bind("<B1-Motion>", self._resize_console)
        d_grip.bind("<Enter>", lambda e: d_grip.configure(fg_color=BRAND))
        d_grip.bind("<Leave>", lambda e: d_grip.configure(fg_color=BORDER))

        drawer_header = ctk.CTkFrame(self._drawer, fg_color=CARD_ELEVATED,
                                     height=32, corner_radius=0)
        drawer_header.pack(fill="x")
        drawer_header.pack_propagate(False)
        ctk.CTkLabel(drawer_header, text="●  OUTPUT", font=(UI_FONT, 11, "bold"),
                     text_color=GREEN).pack(side="left", padx=12)
        collapse_btn = ctk.CTkButton(drawer_header, text="▾  Collapse",
                      width=88, height=24, font=(UI_FONT, 11, "bold"),
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      corner_radius=theme.RADIUS_SM,
                      command=self._toggle_console)
        collapse_btn._busy_exempt = True
        collapse_btn.pack(side="right", padx=(2, 8), pady=4)
        clear_btn = ctk.CTkButton(drawer_header, text="Clear", width=54,
                      height=24, font=(UI_FONT, 11), fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER, corner_radius=theme.RADIUS_SM,
                      command=self._clear_console)
        clear_btn._busy_exempt = True
        clear_btn.pack(side="right", padx=2, pady=4)
        self._console = ctk.CTkTextbox(
            self._drawer, font=(MONO_FONT, 11), fg_color=CONSOLE_BG,
            text_color=TEXT_MUTED, corner_radius=0)
        self._console.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self._console.configure(state="disabled")

        # create pages
        for label, cls in nav:
            p = cls(self.content, self)
            self.pages[label] = p
        # Settings isn't a nav-list item — it's reached via the footer gear —
        # so register its page explicitly.
        self.pages["Settings"] = SettingsPage(self.content, self)

        self._show("PSO Tickets" if is_admin else "Connections")

    def _show(self, label):
        if self._current:
            self._current.pack_forget()
        p = self.pages[label]
        p.pack(fill="both", expand=True)
        self._current = p
        # Auto-expand the operations category that owns this page so its
        # active indicator is visible even when navigated to programmatically.
        for grp in getattr(self, "_nav_groups", {}).values():
            if label in grp["labels"]:
                grp["expand"]()
        for lbl, btn, bar in self._btns:
            selected = lbl == label
            btn.configure(
                fg_color=SIDEBAR_SEL if selected else "transparent",
                text_color=TEXT if selected else TEXT_MUTED,
                font=(UI_FONT, 12, "bold") if selected else (UI_FONT, 12))
            bar.configure(fg_color=BRAND if selected else "transparent")
        if hasattr(p, "on_show"):
            p.on_show()
        elif hasattr(p, "_console_var"):
            pass  # page will set it via on_show
        else:
            self.set_active_console("")

    def _iter_buttons(self, widget):
        """Yield every CTkButton in the widget tree under `widget`."""
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkButton):
                yield child
            yield from self._iter_buttons(child)

    def set_busy(self, busy: bool, allow=()):
        """Lock the UI during a critical operation (backup/restore).

        Every button is disabled except those in `allow` (the running page
        keeps managing its own Start/Stop/Skip/etc.) and any marked
        `_busy_exempt` (the OUTPUT drawer controls, so the log stays usable).
        Prior states are saved on lock and restored on unlock — including the
        sidebar nav, so the user can't switch pages mid-run.
        """
        allow_ids = {id(w) for w in allow}
        if busy:
            # Re-entry guard: a second lock without an intervening unlock would
            # snapshot the already-disabled states and leave the UI stuck
            # disabled forever after the eventual unlock. Ignore redundant locks.
            if self._busy:
                return
            self._busy = True
            self._saved_btn_states = {}
            for w in self._iter_buttons(self):
                if id(w) in allow_ids or getattr(w, "_busy_exempt", False):
                    continue
                try:
                    self._saved_btn_states[w] = w.cget("state")
                    w.configure(state="disabled")
                except Exception:
                    pass
        else:
            self._busy = False
            for w, st in self._saved_btn_states.items():
                try:
                    w.configure(state=st)
                except Exception:
                    pass  # widget may have been destroyed/rebuilt
            self._saved_btn_states = {}

    def connect(self, role):
        ctx = self.cfg.get_by_role(role)
        if not ctx:
            return
        api = S1API(ctx.url, ctx.api_token,
                    verify_ssl=not getattr(ctx, "ignore_ssl_errors", False))
        # Surface API rate-limiting so a slow backup/restore explains itself
        # instead of looking hung. Throttled at most once every ~10 events to
        # avoid flooding the log on a heavily-limited tenant.
        def _on_throttle(info, _r=role):
            if info.get("events", 0) % 10 == 1:
                cli_log(f"⏳ {_r} console is rate-limiting us "
                        f"(429 ×{info['events']}); backing off and retrying — "
                        f"this is normal on large tenants.", "warning")
        api.on_throttle = _on_throttle
        if role == "source":
            self.source_api = api
            self.src_lbl.configure(
                text=f"{ctx.name}\n{ctx.display_url}", text_color=GREEN)
        else:
            self.dest_api = api
            self.dst_lbl.configure(
                text=f"{ctx.name}\n{ctx.display_url}", text_color=ACCENT)

    def log_audit(self, action, **fields):
        """Append one operation to the audit history (best-effort)."""
        try:
            self.audit.record(
                action, when=datetime.now().isoformat(timespec="seconds"),
                **fields)
        except Exception:
            pass

    def set_active_console(self, role: str):
        """Highlight which console (source/destination) is active for current operation."""
        if role == "source":
            self._src_frame.configure(fg_color=theme.GREEN_BG)
            self._dst_frame.configure(fg_color="transparent")
            self._active_lbl.configure(
                text="▶  ACTIVE: SOURCE", text_color=GREEN)
        elif role == "destination":
            self._src_frame.configure(fg_color="transparent")
            self._dst_frame.configure(fg_color=theme.ACCENT_BG)
            self._active_lbl.configure(
                text="▶  ACTIVE: DESTINATION", text_color=ACCENT)
        else:
            self._src_frame.configure(fg_color="transparent")
            self._dst_frame.configure(fg_color="transparent")
            self._active_lbl.configure(text="", text_color=TEXT_FAINT)

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
        # Mirror the latest line into the always-visible status bar so the log
        # is glanceable even while the drawer is collapsed.
        if level != "banner":
            preview = line.strip()
            if len(preview) > 90:
                preview = preview[:90] + "…"
            color = {"error": ACCENT, "warning": WARN,
                     "success": GREEN}.get(level, TEXT_FAINT)
            self._log_preview.configure(text=preview, text_color=color)

    def _clear_console(self):
        self._console.configure(state="normal")
        self._console.delete("1.0", "end")
        self._console.configure(state="disabled")

    def show_console(self):
        """Ensure the OUTPUT drawer is open (e.g. after a ? help click)."""
        if not self._console_visible:
            self._toggle_console()
        else:
            self._console.see("end")

    def _toggle_console(self):
        """Slide the OUTPUT drawer up over the page, or tuck it away.
        Collapsed, the latest log line still shows in the status bar."""
        if self._console_visible:
            self._drawer.pack_forget()
            self._drawer_btn.configure(text="▴  OUTPUT")
            self._console_visible = False
        else:
            # side=bottom after the status bar → drawer sits just above it
            self._drawer.pack(side="bottom", fill="x")
            self._drawer_btn.configure(text="▾  OUTPUT")
            self._console_visible = True
            self._console.see("end")

    def _resize_console(self, event):
        """Drag the grip on the drawer's top edge to set its height."""
        # Drawer bottom edge sits just above the 30px status bar; height is the
        # gap from the pointer up to that edge.
        y_in_win = self.winfo_pointery() - self.winfo_rooty()
        drawer_bottom = self.winfo_height() - 30
        new_h = max(120, min(self.winfo_height() - 160, drawer_bottom - y_in_win))
        self._drawer_h = new_h
        self._drawer.configure(height=new_h)

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
