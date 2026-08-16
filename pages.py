"""
Backup, Restore, and Agent Migration pages.
"""
import copy
import customtkinter as ctk
import json
import os
import unicodedata
from collections import Counter
from tkinter import filedialog, messagebox
from datetime import datetime, timezone
from typing import Optional

import theme
from app import (run_async, LogBox, CARD, GREEN, GREEN_HOVER, ACCENT,
                 ACCENT_HOVER, WARN, WARN_HOVER, INFO, cli_log,
                 _ConsoleProxy, _help_btn, _ToolTip, UI_FONT, MONO_FONT, BRAND,
                 BRAND_HOVER, CARD_ELEVATED, BORDER, NEUTRAL, NEUTRAL_HOVER,
                 TEXT, TEXT_MUTED, TEXT_FAINT, SIDEBAR_BG, CONSOLE_BG)
from export_utils import export_report
from s1_api import S1APIError
from config import APP_VERSION

EXCL_TYPES = ["white_hash", "path", "file_type", "certificate", "browser"]

BACKUP_ELEMENTS = [
    # ── Core config ──
    "policy",
    "exclusions",
    "unified_exclusions",
    "blocklist",
    # ── Firewall ──
    "firewall_rules",
    "firewall_config",
    # ── Network Quarantine ──
    "nq_config",
    "nq_rules",
    # ── Device Control ──
    "device_control_rules",
    "device_control_config",
    # ── Tags ──
    "tags_firewall",
    "tags_network_quarantine",
    "tags_endpoint",
    # ── Detection ──
    "star_rules",
    "saved_filters",
    "threat_intel",
    # ── Config ──
    "config_overrides",
    "log_collection_rules",
    "auto_upgrade_policies",
    "locations",
    # ── Settings ──
    "settings_notifications",
    "settings_sso",
    "settings_smtp",
    "settings_syslog",
    "settings_ad",
    "webhooks",
    "scheduled_reports",
    # ── Users & Roles ──
    "roles",
    "service_users",
    "console_users",
    # ── Other ──
    "gateways",
    "marketplace_apps",
    "scripts",
]

# Elements compared by Migration Validation. Defaults to everything backup
# captures so validation can't silently skip a migrated element — see the
# test_validation_covers_backup_elements guard test which fails if a backup
# element has no comparison category in _summarize_node_payload.
_VALIDATION_ELEMENTS = list(BACKUP_ELEMENTS)


ELEMENT_HELP = {
    "policy": "Endpoint protection policy (mitigation mode, engines, DV settings, etc.)",
    "exclusions": "Legacy exclusion types: hash, path, file type, certificate, browser",
    "unified_exclusions": "Unified Exclusions (v2.1) — includes tag-based exclusions and all "
                          "modern exclusion types. Use this instead of legacy exclusions when "
                          "the source console uses Unified Exclusions.",
    "blocklist": "SHA1/SHA256 hash blocklist (restrictions) entries",
    "firewall_rules": "Firewall Control rules for network traffic filtering",
    "firewall_config": "Firewall Control configuration (enabled, inheritance, location-aware)",
    "nq_config": "Network Quarantine configuration (auto-isolate infected endpoints)",
    "nq_rules": "Network Quarantine allow-rules for quarantined endpoints",
    "device_control_rules": "Device Control rules (USB, Bluetooth block/allow)",
    "device_control_config": "Device Control configuration (enabled, reporting)",
    "tags_firewall": "Firewall rule tags for organizing rules by location",
    "tags_network_quarantine": "Network Quarantine rule tags",
    "tags_endpoint": "Device inventory and unified endpoint tags",
    "star_rules": "STAR Custom Detection rules (S1QL-based threat hunting rules)",
    "saved_filters": "Saved Deep Visibility / SDL search filters",
    "threat_intel": "Threat Intelligence IOC indicators (account level only)",
    "config_overrides": "Persistent agent configuration overrides",
    "log_collection_rules": "XDR log collection rules for 3rd-party data ingestion",
    "auto_upgrade_policies": "Agent auto-upgrade policy schedules",
    "locations": "Network locations used by firewall location-awareness rules",
    "settings_notifications": "Notification settings and email recipients",
    "settings_sso": "SSO / SAML single sign-on configuration",
    "settings_smtp": "SMTP relay settings for email notifications",
    "settings_syslog": "Syslog forwarding configuration",
    "settings_ad": "Active Directory integration settings",
    "webhooks": "Notification webhook endpoints (Slack/Teams/generic HTTP)",
    "scheduled_reports": "Scheduled / saved console reports",
    "roles": "RBAC custom role definitions (account level only)",
    "service_users": "API service user accounts (account level only)",
    "console_users": "Console (human) login users — only locally-created "
                      "users are migrated; SSO/SCIM users auto-provision on "
                      "login. Each created user is sent an invitation email "
                      "by SentinelOne (account level only).",
    "gateways": "Management proxy / gateway configurations",
    "marketplace_apps": "Inventory of installed Singularity Marketplace apps "
                       "(read-only — re-install manually on destination as "
                       "each app requires its own OAuth / credentials)",
    "scripts": "Remote Scripts library (custom scripts). Inventory only — the "
               "script body is held in per-tenant cloud storage and isn't "
               "returned by the API, so each script is listed for manual "
               "re-upload on the destination (account level only).",
}


def _build_elements_section(parent, row, title="Elements"):
    """Build a collapsible elements section with checkboxes and help tooltips.
    Returns (container_frame, elem_vars dict)."""
    collapsed = ctk.BooleanVar(value=True)  # True = collapsed

    # header row
    hdr = ctk.CTkFrame(parent, fg_color="transparent")
    hdr.grid(row=row, column=0, columnspan=2, padx=12, pady=(8, 0), sticky="ew")

    toggle_btn = ctk.CTkButton(
        hdr, text=f"▶ {title} ({len(BACKUP_ELEMENTS)} items — all selected)",
        font=(UI_FONT, 13), fg_color="transparent", hover_color=NEUTRAL_HOVER,
        text_color=TEXT, anchor="w", height=28,
        command=lambda: _toggle())
    toggle_btn.pack(side="left", fill="x", expand=True)

    # content frame (hidden by default)
    content = ctk.CTkFrame(parent, fg_color="transparent")
    # don't grid yet — starts collapsed

    # checkboxes with help tooltips
    elem_vars = {}
    for i, el in enumerate(BACKUP_ELEMENTS):
        var = ctk.BooleanVar(value=True)
        f = ctk.CTkFrame(content, fg_color="transparent")
        f.grid(row=i // 4, column=i % 4, padx=4, pady=1, sticky="w")
        ctk.CTkCheckBox(f, text=el, variable=var,
                        font=(UI_FONT, 10), width=20).pack(
            side="left")
        help_text = ELEMENT_HELP.get(el, "")
        if help_text:
            tip = ctk.CTkLabel(f, text="ⓘ", font=(UI_FONT, 10),
                               text_color=TEXT_FAINT, cursor="hand2", width=16)
            tip.pack(side="left", padx=(2, 0))
            tt = _ToolTip(tip, f"{el}: {help_text}", wraplength=300)
            tip.bind("<Enter>", lambda e, w=tip:
                     w.configure(text_color=INFO), add="+")
            tip.bind("<Leave>", lambda e, w=tip:
                     w.configure(text_color=TEXT_FAINT), add="+")
            tip.bind("<Button-1>", lambda e, t=tt: t._toggle(), add="+")
        elem_vars[el] = var

    # select all / deselect all
    sel_frame = ctk.CTkFrame(content, fg_color="transparent")
    sel_frame.grid(row=len(BACKUP_ELEMENTS) // 4 + 1, column=0,
                   columnspan=4, pady=(4, 4), sticky="w")
    ctk.CTkButton(sel_frame, text="Select All", width=80, height=24,
                  font=(UI_FONT, 10), fg_color=NEUTRAL,
                  command=lambda: _update_all(True)
                  ).pack(side="left", padx=(0, 6))
    ctk.CTkButton(sel_frame, text="Deselect All", width=80, height=24,
                  font=(UI_FONT, 10), fg_color=NEUTRAL,
                  command=lambda: _update_all(False)
                  ).pack(side="left")

    def _count_selected():
        n = sum(1 for v in elem_vars.values() if v.get())
        return n

    def _update_header():
        n = _count_selected()
        arrow = "▼" if not collapsed.get() else "▶"
        toggle_btn.configure(
            text=f"{arrow} {title} ({n}/{len(BACKUP_ELEMENTS)} selected)")

    def _update_all(val):
        for v in elem_vars.values():
            v.set(val)
        _update_header()

    def _toggle():
        if collapsed.get():
            collapsed.set(False)
            content.grid(row=row + 1, column=0, columnspan=2,
                         padx=12, pady=(0, 8), sticky="ew")
        else:
            collapsed.set(True)
            content.grid_forget()
        _update_header()

    # track checkbox changes to update header count
    for var in elem_vars.values():
        var.trace_add("write", lambda *a: _update_header())

    _update_header()
    return hdr, elem_vars


class ProgressTable(ctk.CTkFrame):
    """Live-updating progress table for backup/restore operations.

    Rolled-our-own scrollable container: an outer `tk.Canvas` + vertical
    `tk.Scrollbar`, with an inner CTkFrame containing the rows. We bypass
    `CTkScrollableFrame` entirely because its layout fights with
    `tk.PanedWindow` (the real Tk path is nested under an internal canvas,
    so siblings can't see it) and its mouse-wheel binding fails to reach
    nested CTkLabel widgets.
    """

    # (bg, fg) per status; each is a (light, dark) pair — CTk labels accept them.
    STATUS_COLORS = {
        "pending":  (("#E4E7EC", "#444"),    ("#5A6270", "#888")),
        "running":  (("#DBEAFE", "#1a3a5c"), ("#1D4ED8", "#4da6ff")),
        "done":     (("#D1FAE5", "#0d3b2e"), ("#047857", "#00b894")),
        "error":    (("#FFE4E6", "#3b0d1e"), ("#BE123C", "#e94560")),
        "skipped":  (("#E4E7EC", "#333"),    ("#8A909C", "#666")),
    }

    def __init__(self, master, height: int = 300, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        super().__init__(master, **kw)
        import tkinter as _tk

        self._rows = {}
        self._row_idx = 0

        # Outer canvas (the scrollable viewport).
        self._canvas = _tk.Canvas(
            self, highlightthickness=0, bd=0, height=height)
        theme.tk_track(self._canvas,
                       lambda w: w.configure(bg=theme.tkcolor(CARD)))
        self._vscroll = _tk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Inner frame — every row goes inside this.
        self._inner = ctk.CTkFrame(self._canvas, fg_color="transparent",
                                    corner_radius=0)
        self._inner_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")
        # When the inner content's bounding box changes, update the
        # canvas scrollregion (otherwise the scrollbar thinks there's
        # nothing to scroll).
        self._inner.bind("<Configure>", self._on_inner_configure)
        # When the canvas itself is resized, stretch the inner frame to
        # match its width so column-weighted children expand correctly.
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # Wheel scrolling on the canvas + any descendant (see _bind_wheel).
        self._bind_wheel(self._canvas)
        self._bind_wheel(self._inner)

        # Header row inside the inner frame.
        ctk.CTkLabel(self._inner, text="Node",
                     font=(UI_FONT, 10, "bold"),
                     text_color=TEXT_MUTED, width=250).grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="w")
        ctk.CTkLabel(self._inner, text="Status",
                     font=(UI_FONT, 10, "bold"),
                     text_color=TEXT_MUTED, width=70).grid(
            row=0, column=1, padx=4, pady=4)
        ctk.CTkLabel(self._inner, text="Details",
                     font=(UI_FONT, 10, "bold"),
                     text_color=TEXT_MUTED).grid(
            row=0, column=2, padx=(4, 8), pady=4, sticky="w")
        self._inner.grid_columnconfigure(2, weight=1)

        # Re-compute detail-label wraplength on resize.
        self.bind("<Configure>", self._on_configure_relayout)
        self._canvas.bind("<Configure>", self._on_configure_relayout, add="+")

    # ── scrolling plumbing ────────────────────────────────────────────

    def _on_inner_configure(self, _evt=None):
        # Inner content grew/shrunk → recompute scrollable region.
        bbox = self._canvas.bbox("all")
        if bbox:
            self._canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event):
        # Stretch the inner frame to fill the canvas width so column
        # weight=1 children actually expand.
        self._canvas.itemconfigure(self._inner_window, width=event.width)

    def _bind_wheel(self, widget):
        """Bind mouse-wheel and arrow-keys to scroll the inner canvas.
        Tkinter's wheel events are platform-specific:
          • macOS:   `<MouseWheel>` with delta of ±1/2 per notch.
          • Windows: `<MouseWheel>` with delta of ±120 per notch.
          • X11:     `<Button-4>` (up) / `<Button-5>` (down).
        Calling `add='+'` keeps any existing bindings intact.
        """
        def on_wheel(event):
            d = getattr(event, "delta", 0)
            if d:
                step = -1 if d > 0 else 1
                if abs(d) >= 120:        # Windows
                    step = -1 * int(d / 120)
            else:                        # X11
                step = -1 if event.num == 4 else 1
            self._canvas.yview_scroll(step, "units")
            return "break"

        widget.bind("<MouseWheel>", on_wheel, add="+")
        widget.bind("<Button-4>", on_wheel, add="+")
        widget.bind("<Button-5>", on_wheel, add="+")
        # Arrow keys when the canvas has focus.
        widget.bind("<Up>",   lambda _e: (self._canvas.yview_scroll(-1, "units"), "break"), add="+")
        widget.bind("<Down>", lambda _e: (self._canvas.yview_scroll( 1, "units"), "break"), add="+")
        widget.bind("<Prior>", lambda _e: (self._canvas.yview_scroll(-1, "pages"), "break"), add="+")
        widget.bind("<Next>",  lambda _e: (self._canvas.yview_scroll( 1, "pages"), "break"), add="+")

    def _on_configure_relayout(self, event=None):
        try:
            total_w = self.winfo_width()
        except Exception:
            return
        # Subtract Node (~240px), Status (~80px), padding (~40px).
        avail = max(180, total_w - 360)
        for row in self._rows.values():
            try:
                row["detail"].configure(wraplength=avail)
                row["name"].configure(wraplength=max(200, total_w - avail - 120))
            except Exception:
                pass

    def clear(self):
        for widgets in self._rows.values():
            for w in widgets.values():
                w.destroy()
        self._rows = {}
        self._row_idx = 0

    @staticmethod
    def _short_path(path: str, ntype: str) -> str:
        """Trim the redundant account/site prefix so long enterprise
        paths don't eat the whole row. Full path stays in the tooltip."""
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return path
        if ntype == "account":
            return parts[0]
        if ntype == "site":
            return parts[-1]
        if ntype == "group":
            # site / group   — drops the account prefix.
            return " / ".join(parts[-2:])
        return parts[-1]

    def add_node(self, node_id: str, path: str, ntype: str = ""):
        """Add a pending row. Returns node_id for later updates."""
        self._row_idx += 1
        r = self._row_idx
        prefix = {"global": "●", "account": "▸",
                  "site": "  ▹", "group": "    ◦"}.get(ntype, "")
        bg, fg = self.STATUS_COLORS["pending"]

        display = self._short_path(path, ntype)
        # Numbered index — same as diff panel ordering. Padded to 3 chars
        # so paths stay vertically aligned no matter how many rows there
        # are.
        name_lbl = ctk.CTkLabel(self._inner,
                                text=f"{r:>3}. {prefix} {display}",
                                font=(MONO_FONT, 11), text_color=TEXT,
                                anchor="w")
        name_lbl.grid(row=r, column=0, padx=(8, 4), pady=1, sticky="ew")
        # Hover-tooltip: show the FULL path on mouse-over so the operator
        # can confirm what scope this row belongs to.
        self._attach_tooltip(name_lbl, path)

        status_lbl = ctk.CTkLabel(self._inner, text="pending",
                                  font=(UI_FONT, 10, "bold"),
                                  fg_color=bg, text_color=fg,
                                  corner_radius=6, width=70, height=22)
        status_lbl.grid(row=r, column=1, padx=4, pady=1)

        # wraplength=0 disables wrap on CTkLabel; pass a positive value so
        # long element-summary strings spill onto a second line instead of
        # being clipped. Re-computed on resize via _on_configure.
        detail_lbl = ctk.CTkLabel(self._inner, text="",
                                  font=(MONO_FONT, 10), text_color=TEXT_MUTED,
                                  anchor="w", justify="left",
                                  wraplength=380)
        detail_lbl.grid(row=r, column=2, padx=(4, 8), pady=1, sticky="ew")

        # Forward wheel events on each row widget to the outer canvas so
        # the cursor-position doesn't matter for trackpad/wheel scrolling.
        for w in (name_lbl, status_lbl, detail_lbl):
            self._bind_wheel(w)

        self._rows[node_id] = {
            "name": name_lbl, "status": status_lbl, "detail": detail_lbl}
        return node_id

    def _attach_tooltip(self, widget, text: str):
        """Lightweight Tk tooltip — pops up after a brief hover."""
        import tkinter as _tk
        tip = {"win": None, "after_id": None}

        def show(_evt=None):
            if tip["win"] is not None:
                return
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            w = _tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry(f"+{x}+{y}")
            lbl = _tk.Label(
                w, text=text, justify="left",
                background=theme.tkcolor(CARD_ELEVATED),
                foreground=theme.tkcolor(TEXT),
                relief="solid", borderwidth=1,
                font=(MONO_FONT, 10), padx=6, pady=3)
            lbl.pack()
            tip["win"] = w

        def schedule(_evt=None):
            tip["after_id"] = widget.after(450, show)

        def hide(_evt=None):
            if tip["after_id"]:
                try:
                    widget.after_cancel(tip["after_id"])
                except Exception:
                    pass
                tip["after_id"] = None
            if tip["win"] is not None:
                try:
                    tip["win"].destroy()
                except Exception:
                    pass
                tip["win"] = None

        widget.bind("<Enter>", schedule)
        widget.bind("<Leave>", hide)
        widget.bind("<Button-1>", hide)

    def set_running(self, node_id: str):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["running"]
        row["status"].configure(text="running", fg_color=bg, text_color=fg)
        row["name"].configure(text_color=TEXT)
        # Auto-scroll so the active row is always visible. Defer one tick
        # so Tk has finished laying out the just-configured label widths.
        self.after(20, lambda r=row: self._scroll_to_widget(r["name"]))

    def _scroll_to_widget(self, widget):
        """Scroll the inner canvas so `widget` is visible inside the
        viewport, near the top third."""
        try:
            self.update_idletasks()
            canvas = self._canvas
            wy = widget.winfo_y()           # y inside _inner
            wh = widget.winfo_height() or 22
            inner_h = max(1, self._inner.winfo_height())
            view_top, view_bot = canvas.yview()
            current_top_px = view_top * inner_h
            current_bot_px = view_bot * inner_h
            # Only scroll if the row isn't comfortably in view already.
            if wy < current_top_px + 20 \
                    or (wy + wh) > current_bot_px - 20:
                target = max(0.0, (wy - 40) / inner_h)
                target = min(target, 1.0)
                canvas.yview_moveto(target)
        except Exception:
            pass

    def set_done(self, node_id: str, summary: str = ""):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["done"]
        row["status"].configure(text="done", fg_color=bg, text_color=fg)
        row["name"].configure(text_color=TEXT_MUTED)
        if summary:
            row["detail"].configure(text=summary, text_color=GREEN)

    def set_error(self, node_id: str, msg: str = ""):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["error"]
        row["status"].configure(text="error", fg_color=bg, text_color=fg)
        if msg:
            row["detail"].configure(text=msg, text_color=ACCENT)

    def set_skipped(self, node_id: str, reason: str = ""):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["skipped"]
        row["status"].configure(text="skip", fg_color=bg, text_color=fg)
        row["name"].configure(text_color=TEXT_FAINT)
        if reason:
            row["detail"].configure(text=reason, text_color=TEXT_FAINT)

    def set_detail(self, node_id: str, text: str):
        row = self._rows.get(node_id)
        if row:
            row["detail"].configure(text=text, text_color=TEXT_MUTED)


# Fields to strip from source objects before creating on destination
_STRIP_FIELDS = {
    # identifiers & timestamps
    "id", "createdAt", "updatedAt", "createdAt__gt", "createdAt__lt",
    "lastModified",
    # user references
    "creator", "creatorId", "updater", "updaterId",
    "userId", "userName", "userFullName",
    # scope references (destination scope is passed separately)
    # `scopeLevel` is what /filters reports ('account' / 'site' / 'global').
    # Saved filters are created with the destination scope in the request's
    # `filter` envelope, so leaving the SOURCE scopeLevel in `data` contradicts
    # it and S1 rejects the create — which silently left every migrated site
    # with no filters, and therefore every dynamic group downgraded to static.
    "scope", "scopeName", "scopePath", "scopeId", "scopeLevel",
    "accountId", "accountName", "siteId", "siteName",
    "groupId", "groupName",
    # read-only computed fields
    "imported", "editable", "inAppInventory", "notRecommended",
    "generatedAlerts", "lastAlertTime", "reachedLimit",
    "statusReason", "expired", "source",
    "reportingAgents", "activeFirewallRules",
    # STAR-rule read-only flag: the GET returns `activeResponse` (whether
    # the rule has an auto-response / RemoteOps action) but the create
    # endpoint rejects it with "data: dict_values(['activeResponse']):
    # Unknown field (code 4000010)".
    "activeResponse",
    # site/group read-only
    "activeLicenses", "activeAgents", "totalAgents",
    "registrationToken", "healthStatus", "numberOfSites",
    "agentsInCompleteSku", "agentsInControlSku", "agentsInCoreSku",
    "completeSites", "controlSites", "coreSites",
    "totalComplete", "totalControl", "totalCore",
    "unlimitedComplete", "unlimitedControl", "unlimitedCore",
    "salesforceId", "makeSocDefaultUi",
    # settings read-only
    "ssoElevatedSessionReauthTypeEnabled",
    "ssoInheritableDomains", "ssoEl",
}


def _clean_for_restore(obj: dict) -> dict:
    """Remove source-specific fields before pushing to destination."""
    return {k: v for k, v in obj.items() if k not in _STRIP_FIELDS}


# Read-only / scope-binding fields that must never appear inside a role's
# create `data`. The scope lives in the top-level `filter` instead, and S1
# rejects every one of these in `data` with "Unknown field (code 4000010)".
_ROLE_DATA_READONLY = {
    "id", "createdAt", "updatedAt", "createdBy", "created_by_id",
    "created_by_name", "creator", "creatorId",
    "updatedBy", "updatedById", "updater", "updaterId",
    "usersInRole", "usersInRoles", "users",
    "predefined", "predefinedRole", "editable", "inherited", "inheritedFrom",
    "accountId", "accountName", "accountIds",
    "siteId", "siteName", "siteIds",
    "groupId", "groupName", "groupIds",
    "scope", "scopeId", "scopeName",
}

# Possible boolean keys on a single permission "action" across S1 schema
# variants (the GET role uses one name, the create template may use another).
_ACTION_BOOL_KEYS = ("isEnabled", "isAllowed", "enabled", "allowed", "value",
                     "checked", "granted")


def _role_scope_filter(dest_account_id: str = "", dest_site_id: str = "") -> dict:
    """Top-level `filter` that binds a new role to the destination scope."""
    if dest_site_id:
        return {"siteIds": [dest_site_id]}
    if dest_account_id:
        return {"accountIds": [dest_account_id]}
    return {}


def _perm_ident(d: dict) -> str:
    """Stable identifier for a permission group / action, matched across
    consoles by name (falls back to id/key). Role IDs never match across
    consoles but the permission taxonomy names do."""
    if not isinstance(d, dict):
        return ""
    return str(d.get("name") or d.get("id") or d.get("key") or "").strip().lower()


def _action_bool_key(d: dict):
    """Return the boolean field name present on an action/group dict, if any."""
    if not isinstance(d, dict):
        return None
    for k in _ACTION_BOOL_KEYS:
        if k in d and isinstance(d[k], bool):
            return k
    return None


def _child_action_list(group: dict):
    """The nested list of action dicts inside a permission group."""
    if not isinstance(group, dict):
        return None
    acts = group.get("actions")
    if isinstance(acts, list) and all(isinstance(x, dict) for x in acts):
        return acts
    # Fall back to the first list-of-dicts value (schema-name agnostic).
    for v in group.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return v
    return None


def _find_permission_list(data: dict):
    """Find the top-level list of permission groups in a role/template dict."""
    if not isinstance(data, dict):
        return None
    for k in ("pages", "roles", "permissions", "features", "groups"):
        v = data.get(k)
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return v
    for v in data.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return v
    return None


def _build_source_perm_lookup(pages) -> dict:
    """{group_ident: {action_ident: bool, "__self__": bool}} from a source
    role's permission grants."""
    lookup: dict = {}
    for g in pages or []:
        if not isinstance(g, dict):
            continue
        gid = _perm_ident(g)
        if not gid:
            continue
        amap: dict = {}
        gkey = _action_bool_key(g)
        if gkey is not None:
            amap["__self__"] = bool(g.get(gkey))
        for a in (_child_action_list(g) or []):
            aid = _perm_ident(a)
            akey = _action_bool_key(a)
            if aid and akey is not None:
                amap[aid] = bool(a.get(akey))
        lookup[gid] = amap
    return lookup


def _overlay_role_permissions(template_data: dict, role_def: dict) -> None:
    """Copy the source role's granted permissions onto the destination
    template in place, matching groups/actions by name. Only permissions the
    destination actually exposes (present in the template) are set, so a
    license mismatch can never inject an unknown permission."""
    src = role_def.get("pages")
    if not isinstance(src, list):
        return
    tmpl_list = _find_permission_list(template_data)
    if not tmpl_list:
        return
    lookup = _build_source_perm_lookup(src)
    for g in tmpl_list:
        amap = lookup.get(_perm_ident(g))
        if not amap:
            continue
        gkey = _action_bool_key(g)
        if gkey is not None and "__self__" in amap:
            g[gkey] = amap["__self__"]
        for a in (_child_action_list(g) or []):
            akey = _action_bool_key(a)
            if akey is None:
                continue
            av = amap.get(_perm_ident(a))
            if av is not None:
                a[akey] = av


def _build_role_payload(role_def: dict, template=None) -> dict:
    """Build the create `data` for a custom RBAC role.

    Preferred path: start from the destination's own role template (the
    create-ready skeleton returned by GET /rbac/role for the target scope),
    stamp the source name/description, and overlay the source's granted
    permissions. This is authoritative for the destination schema and its
    licensed permission set, so it survives console-to-console differences.

    Fallback (no template available): a minimal name/description payload.
    """
    role_def = role_def or {}
    if isinstance(template, dict) and template:
        data = copy.deepcopy(template)
        for k in list(data.keys()):
            if k in _ROLE_DATA_READONLY:
                data.pop(k, None)
        data["name"] = role_def.get("name")
        desc = role_def.get("description")
        if desc is not None:
            data["description"] = desc
        _overlay_role_permissions(data, role_def)
        return data
    data = {"name": role_def.get("name")}
    desc = role_def.get("description")
    if desc is not None:
        data["description"] = desc
    return data


def _drop_forensics_triggering(policy: dict) -> dict:
    """Return a copy of a policy without its `forensicsAutoTriggering` block.

    That block enables the agent to auto-run a RemoteOps forensic-collection
    script on detection, and it references the script *profiles* by ID
    (`windowsProfileId` / `macosProfileId` / `linuxProfileId`). Those
    profiles live on the SOURCE console and don't exist on the destination,
    so pushing the source policy verbatim is rejected with "Bad
    auto-triggering policy information provided (code 4000010)". Dropping the
    block lets the destination keep its own default (auto-triggering
    disabled); the operator can re-point it once the profiles are recreated.
    """
    return {k: v for k, v in policy.items() if k != "forensicsAutoTriggering"}


def _scope_inherits_config(node: dict, cfg) -> bool:
    """True when the SOURCE scope inherited this config (Firewall / Device
    Control / Network Quarantine) from its parent.

    Re-pushing an inherited config onto a destination scope that also
    inherits is unnecessary AND rejected by S1 with:
      "Cannot change firewall settings while inheriting settings from
       parent (code 4000010)".
    Two signals, either of which means "inherited":
      * the source group node carries `inherits: true` (it inherits all
        config from its parent group/site), or
      * the config object itself names an `inheritedFrom` scope.
    """
    grp = node.get("group") or {}
    if grp.get("inherits") is True:
        return True
    if isinstance(cfg, dict) and cfg.get("inheritedFrom"):
        return True
    return False


def _clean_sso_for_restore(obj: dict) -> dict:
    """Clean SSO settings for restore.

    On top of the normal source-field stripping, this drops any key whose
    value is `null`. The /settings/sso endpoint validates nullable fields
    strictly: a disabled feature comes back from the source as
    `autoProvisioning: null`, but PUTting that null back is rejected with
    "data: autoProvisioning: Field may not be null. (code 4000010)".
    Omitting the key entirely lets the destination keep its own default.
    """
    return {k: v for k, v in _clean_for_restore(obj).items() if v is not None}


# SSO fields that are bound to the SOURCE tenant's console URL / SP identity.
# These are generated per-tenant by SentinelOne, so copying a source value to
# a different destination tenant makes /settings/sso return a 5xx. They are
# stripped on a retry so the destination keeps its own SP-side values while
# the portable IdP-side values (certificate, login URL, issuer) still apply.
_SSO_SP_BOUND = {
    "spEntityId", "spAcsUrl", "acsUrl", "samlAcsUrl",
    "spMetadataUrl", "metadataUrl", "spInitiatedLoginUrl",
    "samlSpInitiatedUrl", "redirectUrl", "consoleUrl",
    "audience", "audienceUri", "spIssuer", "replyUrl",
}


# ── Error explanation knowledge base ───────────────────────────────────
# Each entry maps a regex (matched against the lowercased error text) to a
# structured explanation the GUI can show the operator.
# Order matters — the first match wins, so put the more specific patterns
# above the generic ones.
import re as _re

_ERROR_RULES = [
    {
        "match": _re.compile(r"hash .* already exists|already exists.*hash"),
        "what": "Duplicate hash on destination",
        "why":  "This SHA1/SHA256 hash is already in the destination's "
                "blocklist or hash-exclusion list — most likely from a "
                "previous restore or because both consoles share the same "
                "Threat Intel feed.",
        "fix":  "Safe to ignore — the entry exists. No action needed.",
        "severity": "info",
    },
    {
        "match": _re.compile(r"filter with the given name already exists"),
        "what": "Saved DV filter already exists",
        "why":  "A Deep Visibility / SDL saved filter with this name "
                "already exists on the destination at the same scope.",
        "fix":  "Safe to ignore, or rename the destination filter and "
                "re-run the restore if you want both versions.",
        "severity": "info",
    },
    {
        "match": _re.compile(r"rule with same name|rule with the same name"),
        "what": "Duplicate rule name on destination",
        "why":  "A firewall, device-control or STAR rule with the same name "
                "already exists in this scope. S1 enforces unique names per "
                "scope.",
        "fix":  "Safe to ignore unless the destination rule's contents "
                "differ. To force replace, delete the destination rule "
                "first and re-run.",
        "severity": "info",
    },
    {
        "match": _re.compile(
            r"cannot update other settings without marking "
            r"scope as decoupled|marking scope.*decoupled|"
            r"cannot change (firewall|device control|network "
            r"quarantine) settings while inheriting|"
            r"inheriting settings from parent"),
        "what": "Scope inherits from parent",
        "why":  "The destination group/site inherits this configuration "
                "(Device Control / Firewall / NQ config) from its parent. "
                "S1 blocks per-scope writes until you explicitly 'decouple' "
                "the scope.",
        "fix":  "If the source ALSO inherited at this level, ignore — the "
                "inherited config is already correct.\n"
                "If the source had a custom override here, open the "
                "destination console → this scope → the relevant section "
                "(Firewall Control / Device Control / Network "
                "Quarantine) → click 'Override' / 'Decouple from "
                "parent', then re-run the restore. The migrator now "
                "always creates new groups with inherits=true, so this "
                "step is required when the source overrode at group "
                "level.",
        "severity": "info",
    },
    {
        "match": _re.compile(r"invalid locations? for this scope"),
        "what": "Firewall rule references locations that don't exist on the destination",
        "why":  "The source rule was bound to specific Locations (location-"
                "aware firewall rules). The destination console has "
                "different location IDs for the same logical networks — "
                "S1 location IDs never match across consoles.",
        "fix":  "The migrator now auto-retries by stripping the location "
                "binding so the rule lands as location-agnostic. "
                "After the restore finishes, open the destination "
                "console → Firewall Control → the affected rule → "
                "re-attach the matching Location(s). "
                "(If you see this error AFTER updating to v1.3.1+, the "
                "rule is still being rejected for some other reason — "
                "send the full error to support.)",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"dict_values\(\[.?emails.?\]\).*unknown field|"
                             r"data:\s*emails:\s*unknown field"),
        "what": "Notification recipients payload shape rejected",
        "why":  "Older builds wrapped the recipients list as "
                "`data: {emails: [...]}` but the destination tenant's "
                "API only accepts the list directly. v1.3.1+ uses the "
                "correct shape and falls back automatically.",
        "fix":  "Update to S1 Command Center v1.3.1+ — the new build "
                "sends the right payload and falls back to per-recipient "
                "POSTs if the tenant rejects the bulk PUT. No data is "
                "lost: the recipients list is rebuilt from the backup.",
        "severity": "warning",
    },
    {
        "match": _re.compile(
            r"post /exclusions.*→\s*400|"
            r"data:\s*value:|"
            r"data:\s*pathexclusiontype|"
            r"invalid (path|hash|value)|"
            r"non-printable characters|"
            r"path must (start|end)"),
        "what": "Path / value exclusion rejected by destination validation",
        "why":  "S1 validates each exclusion's path against strict rules: "
                "Windows paths must start with a drive letter or a "
                "supported environment variable (%SystemRoot%, "
                "%ProgramFiles%, %ProgramData%, %SystemDrive%, "
                "%AllUsersProfile%, etc.), folder exclusions must end with "
                "'\\', and file exclusions must include an extension. The "
                "destination version may have stricter validation than the "
                "source.",
        "fix":  "1) Open the full error text (Copy button) — the S1 reason "
                "now appears after 'POST /exclusions → 400'.\n"
                "2) For unsupported env vars, replace with absolute paths "
                "or a vendor-supported variable on the destination.\n"
                "3) If many items fail with the same reason, edit the "
                "source exclusion list and re-export, then re-run the "
                "restore (existing items will be skipped).",
        "severity": "error",
    },
    {
        "match": _re.compile(
            r"exclusionname.*255|name.*exceeds.*max|"
            r"name.*too long|ensure this value has at most 255",
            _re.IGNORECASE),
        "what": "Exclusion name exceeds 255-character API limit",
        "why":  "The SentinelOne UI allows exclusion names longer than "
                "255 characters, but the API rejects them on create. "
                "S1 Command Center now auto-truncates names to 255 chars.",
        "fix":  "Update to the latest S1 Command Center — names are now "
                "automatically truncated to 255 characters on restore. "
                "Re-run the restore.",
        "severity": "warning",
    },
    {
        "match": _re.compile(
            r"post /unified-exclusions.*→\s*400|"
            r"unified.exclusion.*invalid|"
            r"modetype.*required|engines.*required|"
            r"scopelevel.*required",
            _re.IGNORECASE),
        "what": "Unified exclusion rejected by destination validation",
        "why":  "The unified exclusion POST requires fields like "
                "`modeType`, `type`, `engines`, `scopeLevel`, "
                "`scopeLevelId`, `value`, and `recommendation`. The "
                "source exclusion may be missing required fields or "
                "contain values the destination doesn't support.",
        "fix":  "1) Open the full error text (Copy button) to see the "
                "exact S1 rejection reason.\n"
                "2) If the destination doesn't support unified "
                "exclusions, use legacy 'exclusions' instead.\n"
                "3) Tag-based exclusions require the tags to exist on "
                "the destination first — ensure tags are restored "
                "before exclusions.",
        "severity": "error",
    },
    {
        "match": _re.compile(
            r"(templateruleid|treatasthre).*may not be null|star.*field may not be null",
            _re.IGNORECASE),
        "what": "STAR rule sent a null field the destination rejects",
        "why":  "The source STAR custom-detection rule carried "
                "`templateRuleId` or `treatAsThreat` as null (the rule "
                "wasn't based on a template / didn't have a treat-as-"
                "threat action). Older builds POST that null straight "
                "back, and the destination's API refuses it (code "
                "4000010).",
        "fix":  "Update to S1 Command Center v1.4.2+ — the restore now "
                "strips null-valued fields from STAR payloads so the "
                "destination uses its own defaults. Re-run the restore.",
        "severity": "warning",
    },
    {
        "match": _re.compile(
            r'scope.*"global".*not a valid choice|'
            r'overrides.*tenant.*unknown field',
            _re.IGNORECASE),
        "what": "Config override rejected — global scope not supported",
        "why":  "The source console had tenant-wide (global) config "
                "overrides, but the destination console is a single-"
                "account tenant that doesn't accept `scope=\"global\"` "
                "or `filter.tenant`. The override needs to be re-scoped "
                "to account level.",
        "fix":  "Update to S1 Command Center v1.4.2+ — the restore now "
                "auto-retries global overrides at account scope using the "
                "destination account ID. Re-run the restore.",
        "severity": "warning",
    },
    {
        "match": _re.compile(
            r"password is missing|smtp.*password",
            _re.IGNORECASE),
        "what": "SMTP password cannot be migrated",
        "why":  "The S1 API never returns SMTP passwords in GET "
                "responses (they are write-only secrets). The migrator "
                "therefore cannot capture or replay the password, so the "
                "destination rejects the PUT with 'Password is missing'.",
        "fix":  "After the restore finishes, open the destination "
                "console → Settings → SMTP → re-enter the SMTP password "
                "manually. All other SMTP fields (host, port, sender) "
                "were migrated successfully.",
        "severity": "info",
    },
    {
        "match": _re.compile(r"set-sso.*field may not be null|"
                             r"sso.*may not be null.*4000010|"
                             r"autoprovisioning.*null"),
        "what": "SSO setting sent a null field the destination rejects",
        "why":  "The source tenant returned an SSO sub-setting (e.g. "
                "`autoProvisioning`) as null because that feature was "
                "disabled there. Older builds PUT that null straight back, "
                "and the destination's /settings/sso validation refuses "
                "null values (code 4000010).",
        "fix":  "Update to S1 Command Center v1.3.9+ — the restore now "
                "drops null-valued SSO fields so the destination keeps its "
                "own default. No data is lost: a null field means the "
                "feature was off on the source. Re-run the restore.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"put /settings/sso.*→ 5\d\d|"
                             r"sso.*server could not process"),
        "what": "SSO configuration rejected by destination",
        "why":  "The destination tenant returned an HTTP 5xx when applying "
                "the SAML/SSO settings. Common causes: the destination has "
                "no SSO provisioned yet, the SAML certificate is bound to "
                "the source tenant's URL, or your token lacks the SSO "
                "edit permission.",
        "fix":  "The restore already retries SSO once with the source-"
                "tenant-bound SP fields stripped; this error means even "
                "that was rejected.\n"
                "1) Confirm SSO is enabled for the destination tenant.\n"
                "2) Re-issue the SAML cert/metadata using the destination "
                "URL.\n"
                "3) If you don't need to migrate SSO right now, uncheck "
                "the 'settings_sso' element and re-run.\n"
                "4) If it still fails, copy this error and send it to "
                "SentinelOne Support — server-side log lookup is needed.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"expiration date must be within the next "
                             r"six months"),
        "what": "STAR rule expiration date out of range",
        "why":  "SentinelOne requires a temporary STAR custom-detection "
                "rule's expiration to fall within the next six months. The "
                "source rule carried a date that is already in the past or "
                "more than six months out, which the destination rejects "
                "(code 4000010).",
        "fix":  "Update to the current build — the restore now clamps any "
                "out-of-range STAR expiration to ~5 months ahead before "
                "creating the rule, then re-run. Adjust the date afterwards "
                "in the console if you need a specific expiry.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"filter:\s*accountids:\s*unknown field"),
        "what": "Config override filter rejected accountIds",
        "why":  "The POST /config-override endpoint's scope filter does not "
                "accept `accountIds` for account-scoped overrides (code "
                "4000010). The scope is conveyed in the override body "
                "instead.",
        "fix":  "Update to the current build — the restore now retries the "
                "override create with the rejected filter key removed, then "
                "re-run. If it still fails, the override may need to be "
                "recreated manually (Policy Override.create permission and "
                "Global/Support scope are required).",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"name rename|default-site set/rename|"
                             r"site.*rename"),
        "what": "Default site could not be renamed",
        "why":  "You chose to map the source site onto an existing "
                "destination site (e.g. the auto-created 'Default site') "
                "and have it renamed to the source site name, but the "
                "rename PUT /sites/{id} was rejected. Common causes: the "
                "destination already has another site with that exact name, "
                "the token lacks 'Site Settings.edit', or the site is in a "
                "non-editable state (expiring/deleted).",
        "fix":  "1) Check the destination account for an existing site that "
                "already uses the source name — rename or remove it, then "
                "re-run.\n"
                "2) Confirm your destination token has the Site Settings "
                "edit permission.\n"
                "3) The settings were still restored onto the mapped site; "
                "only the rename failed, so you can also just rename the "
                "site manually in the console.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"at least one identifier must be defined"),
        "what": "Location has no identifiers",
        "why":  "S1 requires every Location to declare at least one "
                "identifier (IP, MAC, DNS suffix, gateway, AD site, or "
                "registry key). The migrator captured a location with an "
                "empty identifier set — usually the per-site 'Fallback' "
                "location, which S1 auto-creates at site creation.",
        "fix":  "Update to S1 Command Center v1.2.0+ — the restore now "
                "skips empty/auto-created locations automatically.\n"
                "If a non-Fallback location triggers this, the source "
                "location was misconfigured; re-create it manually with at "
                "least one identifier.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"filter:.*groupids.*unknown field|"
                             r"unknown field.*groupids"),
        "what": "Element doesn't exist at group scope",
        "why":  "S1 stores this element type (e.g. Locations) only at "
                "Account or Site scope. The migrator tried to write it at "
                "Group scope and the API rejected the `groupIds` filter.",
        "fix":  "Update to S1 Command Center v1.2.0+ — group-scoped writes "
                "for these elements are now skipped automatically. No data "
                "is lost: the parent site already holds the configuration.",
        "severity": "info",
    },
    {
        "match": _re.compile(r"scope.*missing data for required field|"
                             r"missing data for required field.*scope"),
        "what": "Destination scope filter missing",
        "why":  "The destination console wants the override/rule to be "
                "anchored to a scope (account/site/group), but the "
                "migrator didn't include one. This usually means the "
                "S1 Command Center version is out of date.",
        "fix":  "Update to the latest S1 Command Center build (v1.2.0+).\n"
                "If the error persists, copy it and send to the developer.",
        "severity": "error",
    },
    {
        "match": _re.compile(r"insufficient permissions|forbidden|→ 403"),
        "what": "API token lacks the required permission",
        "why":  "Your destination API token doesn't have the role/permission "
                "needed for this action (e.g. 'Policy Override.create', "
                "'Threat Intel.update', 'SSO.edit').",
        "fix":  "1) Open the destination console → Settings → Users → your "
                "service user → Role.\n"
                "2) Grant the missing permission listed in the error.\n"
                "3) Re-issue the API token if you changed the role, then "
                "re-run the restore.",
        "severity": "error",
    },
    {
        "match": _re.compile(r"→ 401|unauthorized"),
        "what": "API token invalid or expired",
        "why":  "The destination token was rejected. It may have expired, "
                "been revoked, or come from a different tenant.",
        "fix":  "Open the destination console → Settings → Users → API "
                "Tokens → generate a fresh token, paste it into the "
                "DESTINATION card, click 'Save & Connect', then re-run.",
        "severity": "error",
    },
    {
        "match": _re.compile(r"→ 404|not found"),
        "what": "Target endpoint or resource not found",
        "why":  "The destination console returned 404. Either the endpoint "
                "isn't enabled on this tenant (e.g. XDR / Marketplace / "
                "Singularity Mobile), or the parent scope (site/group) "
                "wasn't created before this element tried to write to it.",
        "fix":  "1) Confirm the matching product module is licensed on the "
                "destination.\n"
                "2) If it's a per-scope element, re-run after the parent "
                "site/group is fully created.\n"
                "3) Uncheck this element and continue if the feature isn't "
                "in use on the destination.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"→ 429|rate limit|too many requests"),
        "what": "Destination console rate-limited the migration",
        "why":  "The destination API throttled the request bursts. The "
                "migrator retries with backoff, but if the limit is hit "
                "repeatedly, large bulk creates can still fail.",
        "fix":  "Wait a few minutes and re-run — the migrator skips items "
                "that already exist, so a retry is cheap.\n"
                "For very large tenants, run the migration during "
                "off-peak hours.",
        "severity": "warning",
    },
    {
        "match": _re.compile(r"→ 5\d\d|server could not process|"
                             r"internal server error"),
        "what": "Destination console returned a server error (5xx)",
        "why":  "The S1 console itself errored while processing the request. "
                "This is almost always a server-side issue, not a problem "
                "with the migration tool.",
        "fix":  "1) Re-run — many 5xx errors are transient.\n"
                "2) If it persists for the same element, copy this error "
                "(use the Copy button) and send it to SentinelOne Support; "
                "they'll need the timestamp and full URL.\n"
                "3) Meanwhile, uncheck the failing element to let the rest "
                "of the migration complete.",
        "severity": "error",
    },
    {
        "match": _re.compile(r"connection.*refused|connection.*reset|"
                             r"name resolution|nodename nor servname|"
                             r"timed out|read timeout"),
        "what": "Network issue reaching the destination console",
        "why":  "Your machine couldn't talk to the destination URL — DNS "
                "failure, firewall block, VPN drop, or the console URL is "
                "typed wrong.",
        "fix":  "1) Verify the DESTINATION URL in the Connections page.\n"
                "2) Click 'Test' on the DESTINATION card — it should "
                "say 'OK — <your name>'.\n"
                "3) Check VPN/proxy, then re-run the restore.",
        "severity": "error",
    },
    {
        "match": _re.compile(r"ssl|certificate verify failed"),
        "what": "TLS certificate could not be verified",
        "why":  "The destination console's HTTPS certificate didn't pass "
                "verification. Usually means a corporate MITM proxy is "
                "rewriting TLS, or the console is using a self-signed cert.",
        "fix":  "On the DESTINATION connection card, tick the "
                "'Ignore SSL errors' checkbox, click 'Save & Connect', "
                "then re-run the restore.\n"
                "(Only do this if you trust the network between you and "
                "the console.)",
        "severity": "warning",
    },
]


def explain_error(label: str, detail: str, status_code: int = 0) -> dict:
    """Return a structured explanation for a restore error.

    Looks up the first matching rule from `_ERROR_RULES` and decorates it
    with the calling element label and a copy-friendly raw error blob.
    """
    raw = f"[{label}] HTTP {status_code} {detail}".strip()
    text = raw.lower()
    for rule in _ERROR_RULES:
        if rule["match"].search(text):
            return {
                "label":    label,
                "what":     rule["what"],
                "why":      rule["why"],
                "fix":      rule["fix"],
                "severity": rule["severity"],
                "raw":      raw,
            }
    # Fallback: unknown error pattern
    return {
        "label":    label,
        "what":     f"Unrecognised error from '{label}'",
        "why":      "The migration tool doesn't have a specific explanation "
                    "for this error code/message.",
        "fix":      "Copy the raw error using the Copy button below and "
                    "send it to SentinelOne Support (or the migrator "
                    "developer) — include the destination console URL, "
                    "the element name, and the time it happened.",
        "severity": "error",
        "raw":      raw,
    }


# Characters S1's exclusion validator treats as "non-printable" and
# rejects with `Invalid value <x> contains non-printable characters`.
# Source consoles sometimes accumulate these (LTR/RTL marks, zero-width
# joiners, BOMs, etc.) when paths get copy-pasted from rich-text. We
# scrub them on restore so the destination's stricter validator accepts.
_NON_PRINTABLE_RE = _re.compile(
    "[\u0000-\u0008\u000B-\u001F\u007F"   # C0/DEL control chars
    "\u00AD"                              # soft hyphen
    "\u200B-\u200F"                       # zero-width + LTR/RTL marks
    "\u202A-\u202E"                       # bidi embeddings/overrides
    "\u2060-\u206F"                       # word-joiner / invisible ops
    "\uFEFF"                              # BOM / zero-width no-break
    "]")


def _strip_non_printable(s):
    """Return `s` with invisible Unicode control marks removed. The
    backup format keeps strings as-is, but S1's exclusion validator
    rejects any value containing LTR/RTL/BOM/zero-width characters."""
    if not isinstance(s, str):
        return s
    return _NON_PRINTABLE_RE.sub("", s)


def _norm_name(value):
    """Normalise a scope name for comparison: strip invisible marks, apply
    NFKC, casefold and collapse whitespace so filters match regardless of
    case, Unicode form, or stray zero-width characters."""
    value = _strip_non_printable(str(value or ""))
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.casefold().split())


def _select_by_name(items, filt, key=None):
    """Filter `items` by a scope-name filter, preferring EXACT matches.

    A blank filter returns everything. If one or more item names equal the
    filter exactly (after normalisation) only those exact matches are
    returned — so a specific name like "Servers" no longer also selects
    supersets such as "HighQ_Servers" / "TR-Servers". When nothing matches
    exactly, fall back to substring matching for convenience (e.g. "Serv")."""
    nfilt = _norm_name(filt)
    if not nfilt:
        return list(items)
    if key is None:
        def key(it):
            return it
    exact = [it for it in items if _norm_name(key(it)) == nfilt]
    if exact:
        return exact
    return [it for it in items if nfilt in _norm_name(key(it))]


# Whitelists for specific element types that are strict about accepted fields
_EXCL_FIELDS = {
    "type", "value", "osType", "description", "mode",
    "pathExclusionType", "actions", "includeChildren", "includeParents",
}

_UNIFIED_EXCL_FIELDS = {
    "exclusionName", "type", "value", "osType", "description",
    "mode", "modeType", "pathExclusionType", "actions",
    "includeChildren", "includeParents",
    "threatType", "engines", "interactionLevel",
    "reason", "recommendation", "note",
    "conditions", "tagIds", "tagNames",
}

_EXCL_NAME_MAX_LEN = 255

_BLOCKLIST_FIELDS = {
    "type", "value", "osType", "description", "sha256Value",
}

_FW_RULE_FIELDS = {
    # camelCase (API v2.1 format)
    "name", "description", "action", "direction", "protocol",
    "protocolS", "osType", "osTypes", "status", "order",
    "tag", "tagName",
    "localHost", "remoteHost", "localPort", "remotePort",
    # plural host arrays hold multi-IP rules — each entry is
    # {type, values:[...]}. The singular localHost/remoteHost only
    # carries the first host, so dropping these loses every extra IP.
    "localHosts", "remoteHosts",
    "localPortRanges", "remotePortRanges",
    "localHostRanges", "remoteHostRanges",
    "application", "applicationName", "serviceId", "service",
    "location", "locationIds", "locationType",
    "ruleType", "profile",
    # snake_case (CLI backup format)
    "os_types",
    "local_host", "remote_host", "local_port", "remote_port",
    "local_host_type", "remote_host_type",
    "local_port_type", "remote_port_type",
    "remote_hosts", "location_ids", "location_type",
    "application_type", "rule_type",
}

_DC_RULE_FIELDS = {
    "ruleName", "ruleType", "action", "status", "interface",
    "deviceClass", "deviceClassName", "deviceId", "deviceName",
    "vendorId", "productId", "uid", "version", "order",
    "accessPermission", "bluetoothAddress", "gattService",
    "manufacturerName", "minorClasses",
    "deviceInformationServiceInfoKey", "deviceInformationServiceInfoValue",
}

_STAR_RULE_FIELDS = {
    "name", "description", "s1ql", "queryType", "queryLang",
    "severity", "treatAsThreat", "status",
    "expirationMode", "expiration", "networkQuarantine",
}

_SITE_CREATE_FIELDS = {
    "name", "description", "siteType", "suite",
    "unlimitedLicenses", "inherits",
}

_GROUP_CREATE_FIELDS = {
    "name", "description", "inherits", "rank", "policy",
}

# Named /tags objects (firewall, network-quarantine, device-inventory).
# `kind`, `affectedScopes` and `linkedRules` are read-only on the source and
# are rejected by the create endpoint, so they must never be sent.
_TAG_FIELDS = {
    "name", "description", "type", "key", "value", "scope",
}

# Unified endpoint tags (Tag Manager) are key/value pairs on a different
# API — POST /tag-manager with type "endpoints"; `key` is mandatory.
_ENDPOINT_TAG_FIELDS = {
    "key", "value", "description",
}


def _whitelist(obj: dict, allowed: set) -> dict:
    """Keep only allowed fields, strip None values to avoid 'may not be null' errors."""
    return {k: v for k, v in obj.items() if k in allowed and v is not None}


def _rules_for_scope(rules: list, ntype: str) -> list:
    """Keep only rules whose OWN scope matches this node's type.

    The firewall-control and device-control APIs return inherited rules at
    every level (a site query also returns the account/global rules that
    flow down to it). Restoring that raw list re-creates parent-scope rules
    at the child scope — e.g. account firewall rules leaking into a site
    restore even when the Account level is unchecked. The rule's `scope`
    field is one of 'global' / 'account' / 'site' / 'group', which lines up
    1:1 with the node type."""
    return [r for r in (rules or [])
            if str(r.get("scope", "")).lower() == ntype]


def _star_rules_for_scope(rules: list, ntype: str) -> list:
    """STAR variant of _rules_for_scope. Custom-detection rules carry the same
    `scope` field ('account' / 'site' / 'group', and the tenant level reported
    as 'global' or 'tenant'), and /cloud-detection/rules ALSO returns inherited
    rules at every level — so an account rule is returned again under every
    child site. Keep only the rules whose own scope matches this node so one
    account rule isn't backed up (and later re-created) under every site."""
    ok = {"global", "tenant"} if ntype == "global" else {ntype}
    return [r for r in (rules or [])
            if str(r.get("scope", "")).lower() in ok]


def _tags_for_scope(tags: list, ntype: str) -> list:
    """Tag variant of _rules_for_scope. GET /tags also returns the tags this
    scope INHERITS from its parents, so a site query returns the account and
    global tags too. Restoring that raw list re-creates parent tags at every
    child scope. Tags carry the same `scope` field as rules ('global' /
    'account' / 'site' / 'group', with 'tenant' as a global alias).

    Tags with no `scope` field at all are kept: older backups (and some
    consoles) omit it, and dropping them would silently migrate nothing."""
    ok = {"global", "tenant"} if ntype == "global" else {ntype}
    out = []
    for tag in tags or []:
        sc = str(tag.get("scope", "")).strip().lower()
        if not sc or sc in ok:
            out.append(tag)
    return out


def _tag_payload(tag: dict, tag_type: str, ntype: str) -> dict:
    """Create-ready POST /tags `data` block for one backed-up tag.

    Keeps only the writable fields (`kind`/`linkedRules`/`affectedScopes` and
    the id/timestamp block are read-only and rejected), forces the tag type of
    the group being restored, and re-stamps the scope to the destination node
    so an account tag isn't recreated claiming site scope."""
    body = _whitelist(tag or {}, _TAG_FIELDS)
    body["type"] = tag_type
    body["scope"] = "global" if ntype == "global" else ntype
    return body


def _endpoint_tag_payload(tag: dict) -> dict:
    """Create-ready POST /tag-manager `data` block for a unified endpoint tag.
    These are key/value pairs — `key` is mandatory, `value`/`description` are
    optional — and the type is always 'endpoints'."""
    body = _whitelist(tag or {}, _ENDPOINT_TAG_FIELDS)
    body["type"] = "endpoints"
    return body


def _collect_star_rules(api, acct_filter: str = "",
                        site_filter: str = "") -> list:
    """Fetch every STAR custom detection rule the token can see, for export.

    Queries per account (an account query also returns that account's
    descendant site rules), de-dupes by rule id, then applies the Account /
    Site NAME filters using the same exact-preferred matching the backup page
    uses. A Site filter keeps only the rules that live at that site, since
    account/global rules carry no siteName."""
    accounts = api.get_accounts() or []
    if acct_filter:
        accounts = _select_by_name(accounts, acct_filter,
                                   lambda a: a.get("name", ""))
        if not accounts:
            return []

    by_id = {}
    for acct in accounts:
        aid = acct.get("id")
        if not aid:
            continue
        try:
            for rule in api.get_star_rules({"accountIds": [aid]}):
                by_id[str(rule.get("id"))] = rule
        except S1APIError as exc:
            cli_log(f"Could not read STAR rules for "
                    f"{acct.get('name') or aid}: {exc}", "warning")

    rules = list(by_id.values())
    if site_filter:
        rules = _select_by_name(rules, site_filter,
                                lambda r: r.get("siteName") or "")
    return rules


def _scope(scope_type, scope_id):
    """Build scope filter dict. Uses arrays for IDs (required by POST body filters)."""
    if scope_type == "global":
        return {"tenant": "true"}
    elif scope_type == "account":
        return {"accountIds": [scope_id]}
    elif scope_type == "site":
        return {"siteIds": [scope_id]}
    elif scope_type == "group":
        return {"groupIds": [scope_id]}
    return {}


# ─── Restore error classification (pure, module-level for testability) ──
# These were historically nested inside RestorePage._run_restore; they close
# over nothing, so hoisting them lets the test-suite exercise the
# "is this failure actually benign?" logic that drives skip-vs-error counts.

def _is_exists_error(exc) -> bool:
    """Treat duplicate-create and scope-inheritance errors as benign skips
    rather than real failures.
    S1APIError carries the human-readable reason in `.detail`, while
    `str(exc)` is only the short 'METHOD /path → code' line, so we inspect
    both."""
    sc = getattr(exc, "status_code", 0)
    msg = (str(exc) + " " + str(getattr(exc, "detail", ""))).lower()
    exists_words = ("already", "duplicate", "exists",
                    "conflict", "unique",
                    "filter with the given name",
                    "hash",
                    "rule with same name",
                    "with same name")
    # 403 + 'decoupled scope' wording = destination group inherits from its
    # parent, so per-scope writes are blocked. Not a bug — that's the
    # intended inherited-config state.
    inherit_words = ("decoupled", "marking scope",
                     "cannot update other settings")
    if sc in (400, 409) and any(w in msg for w in exists_words):
        return True
    if sc == 403 and any(w in msg for w in inherit_words):
        return True
    return False


def _err_detail(exc) -> str:
    """Best-effort human-readable error text from an exception.
    S1APIError carries `.detail` but the API sometimes returns an empty
    body, leaving detail = ''. Fall back to str(exc) whenever detail is
    missing or blank so the user never sees an empty error."""
    d = getattr(exc, "detail", "") or ""
    if not str(d).strip():
        d = str(exc) or repr(exc)
    return str(d)


def _item_id(item, label="") -> str:
    """Extract a human-readable identifier from a restore item."""
    # Unified endpoint tags are key/value pairs with no name; reporting only
    # the value ("Finance") doesn't say which tag failed.
    if item.get("key") and not item.get("name"):
        val = item.get("value")
        return (f"{item['key']}={val}" if val else str(item["key"]))[:80]
    for key in ("name", "ruleName", "value", "s1ql",
                "email", "fullName", "description", "type"):
        v = item.get(key)
        if v and isinstance(v, str):
            return v[:80]
    return label


# ─── Diff-panel summary helpers ────────────────────────────────────────
# Used by the side-by-side DiffPanel on the Restore page. The same shape
# is produced from a backup node's `data` dict AND from a live destination
# query, so the two columns line up element-by-element.

_CMP_NAME_MAXLEN = 256

# (category, count, top_names[])  — ordering matters: it's the row order
# the panel renders in.
def _summarize_node_payload(data: dict) -> list:
    def _nm(v):
        return str(v)[:_CMP_NAME_MAXLEN]

    out = []
    pol = (data or {}).get("policy") or {}
    if pol:
        mode = "inherit" if pol.get("inheritedFrom") else "custom"
        out.append(("policy", 1, [mode]))
    else:
        out.append(("policy", 0, []))

    excls = (data or {}).get("exclusions") or {}
    if isinstance(excls, dict):
        for etype in EXCL_TYPES:
            items = excls.get(etype) or []
            out.append((f"excl/{etype}", len(items),
                        [_nm(i.get("value", "")) for i in items]))

    u_excls = (data or {}).get("unified_exclusions") or []
    if u_excls:
        out.append(("unified_exclusions", len(u_excls),
                    [_nm(i.get("exclusionName") or i.get("value", ""))
                     for i in u_excls]))

    bl = (data or {}).get("restrictions") \
        or (data or {}).get("blocklist") or []
    out.append(("blocklist", len(bl),
                [_nm(b.get("value", "")) for b in bl]))

    fw = (data or {}).get("firewall", {}) or {}
    fw_rules = fw.get("rules") or []
    out.append(("fw-rules", len(fw_rules),
                [_nm(r.get("name", "")) for r in fw_rules]))
    fw_locs = fw.get("locations") or []
    out.append(("fw-locations", len(fw_locs),
                [_nm(l.get("name", "")) for l in fw_locs]))

    dc = (data or {}).get("deviceControl", {}) or {}
    dc_rules = dc.get("rules") or []
    out.append(("dc-rules", len(dc_rules),
                [_nm(r.get("ruleName") or r.get("name", ""))
                 for r in dc_rules]))

    nq = (data or {}).get("networkQuarantine", {}) or {}
    nq_rules = nq.get("rules") or []
    out.append(("nq-rules", len(nq_rules),
                [_nm(r.get("name", "")) for r in nq_rules]))

    dv = (data or {}).get("deepVisibility", {}) or {}
    flt = dv.get("filters") or (data or {}).get("saved_filters") or []
    out.append(("saved_filters", len(flt),
                [_nm(f.get("name", "")) for f in flt]))

    ovrs = ((data or {}).get("config", {}) or {}).get("overrides") or []
    out.append(("config_overrides", len(ovrs),
                [_nm(o.get("name", "")) for o in ovrs]))

    cusers = (data or {}).get("consoleUsers") or []
    if cusers:
        out.append(("console_users", len(cusers),
                    [_nm(u.get("email") or u.get("fullName", ""))
                     for u in cusers]))

    # ── Detection & hunting ──
    star = (data or {}).get("star") or (data or {}).get("star_rules") or []
    out.append(("star_rules", len(star),
                [_nm(r.get("name", "")) for r in star]))
    ti = (data or {}).get("threatIntel") \
        or (data or {}).get("threat_intel") or []
    out.append(("threat_intel", len(ti),
                [_nm(i.get("value") or i.get("name", "")) for i in ti]))

    # ── Tags ──
    cfg = (data or {}).get("config", {}) or {}
    tags = cfg.get("tags", {}) or {}
    ep_tags = list(tags.get("deviceInventory") or []) \
        + list(cfg.get("endpointTags") or [])
    def _tag_name(t):
        # Named /tags objects carry `name`; unified endpoint tags (Tag
        # Manager) are key/value pairs instead.
        if t.get("name"):
            return _nm(t["name"])
        key = t.get("key") or ""
        val = t.get("value") or ""
        return _nm(f"{key}={val}" if val else key)

    for items, cat in ((tags.get("firewall") or [], "tags_firewall"),
                       (tags.get("networkQuarantine") or [],
                        "tags_network_quarantine"),
                       (ep_tags, "tags_endpoint")):
        out.append((cat, len(items), [_tag_name(t) for t in items]))

    # ── Collections (account / site level) ──
    def _name(x):
        return (x.get("name") or x.get("scriptName") or x.get("email")
                or x.get("applicationName") or x.get("ip")
                or x.get("ipAddress") or x.get("value") or "")
    for key, cat in (("logCollectionRules", "log_collection_rules"),
                     ("autoUpgradePolicies", "auto_upgrade_policies"),
                     ("webhooks", "webhooks"),
                     ("scheduledReports", "scheduled_reports"),
                     ("roles", "roles"),
                     ("serviceUsers", "service_users"),
                     ("gateways", "gateways"),
                     ("marketplaceApps", "marketplace_apps"),
                     ("scripts", "scripts")):
        items = (data or {}).get(key) or []
        out.append((cat, len(items),
                    [_nm(_name(i)) for i in items]))

    # ── Config singletons (presence; value-level diff is out of scope) ──
    fw_cfg = ((data or {}).get("firewall", {}) or {}).get("config")
    out.append(("firewall_config", 1 if fw_cfg else 0, []))
    nq_cfg = ((data or {}).get("networkQuarantine", {}) or {}).get("config")
    out.append(("nq_config", 1 if nq_cfg else 0, []))
    dc_cfg = ((data or {}).get("deviceControl", {}) or {}).get("config")
    out.append(("device_control_config", 1 if dc_cfg else 0, []))

    # ── Settings singletons (presence) ──
    settings = (data or {}).get("settings", {}) or {}
    for skey, scat in (("notifications", "settings_notifications"),
                       ("sso", "settings_sso"), ("smtp", "settings_smtp"),
                       ("syslog", "settings_syslog"),
                       ("activeDirectory", "settings_ad")):
        out.append((scat, 1 if settings.get(skey) else 0, []))
    return out


def _node_identity(node: dict) -> dict:
    """Identity block displayed at the top of each diff column. Pulled
    from a backup node dict — the same shape is built for destination by
    `_dest_identity_from_data`."""
    ntype = node.get("type", "?")
    info = {"type": ntype, "path": node.get("path", "?")}
    if ntype == "group":
        g = node.get("group", {}) or {}
        info["name"] = g.get("name", "?")
        info["group_type"] = g.get("type", "?")
        info["filterId"] = g.get("filterId") \
            or (g.get("filter") or {}).get("id") or ""
        info["filterName"] = g.get("filterName") \
            or (g.get("filter") or {}).get("name") or ""
        info["inherits"] = g.get("inherits", "?")
    elif ntype == "site":
        s = node.get("site", {}) or {}
        info["name"] = s.get("name", "?")
        info["state"] = s.get("state", "?")
        info["siteType"] = s.get("siteType", "?")
    elif ntype == "account":
        a = node.get("account", {}) or {}
        info["name"] = a.get("name", "?")
        info["state"] = a.get("state", "?")
    return info


def _dest_identity_from_data(ntype: str, data: dict) -> dict:
    info = {"type": ntype}
    if ntype == "group":
        g = data.get("_group", {}) or {}
        info["name"] = g.get("name", "?")
        info["group_type"] = g.get("type", "?")
        info["filterId"] = g.get("filterId") \
            or (g.get("filter") or {}).get("id") or ""
        info["filterName"] = g.get("filterName") \
            or (g.get("filter") or {}).get("name") or ""
        info["inherits"] = g.get("inherits", "?")
    elif ntype == "site":
        s = data.get("_site", {}) or {}
        info["name"] = s.get("name", "?")
        info["state"] = s.get("state", "?")
    elif ntype == "account":
        a = data.get("_account", {}) or {}
        info["name"] = a.get("name", "?")
    return info


def _fetch_dest_snapshot(api, ntype: str, dest_id: str,
                         reader=None, elements=None) -> dict:
    """Snapshot a console for one node — shaped the same as a backup `data`
    dict so `_summarize_node_payload` works on both sides. Errors per-element
    are swallowed; missing keys just produce 0-count rows.

    When `reader` is given (the shared BackupPage._read_node), the FULL set of
    backed-up elements is read through the exact same code path backup uses —
    so validation compares everything that migration moves, and can't drift
    from the backup element list. When `reader` is None, only the lightweight
    subset below is read (used by the restore before/after diff panel)."""
    if not dest_id and ntype != "global":
        return {}
    scope = _scope(ntype, dest_id) if ntype != "global" else {"tenant": "true"}
    data: dict = {}
    if ntype == "group":
        try:
            grps = api.get_groups(params={"groupIds": dest_id})
            if grps:
                data["_group"] = grps[0]
        except Exception:
            pass
    elif ntype == "site":
        try:
            sites = api.get_sites(params={"siteIds": dest_id})
            if sites:
                data["_site"] = sites[0]
        except Exception:
            pass
    elif ntype == "account":
        try:
            accts = api.get_accounts()
            for a in accts:
                if str(a.get("id")) == str(dest_id):
                    data["_account"] = a
                    break
        except Exception:
            pass

    # Full, drift-proof read through the shared backup reader.
    if reader is not None:
        try:
            full = reader(api, ntype, dest_id, scope,
                          elements or _VALIDATION_ELEMENTS, None)
            if isinstance(full, dict):
                data.update(full)
        except Exception:
            pass
        return data

    if ntype != "global":
        try:
            data["policy"] = api.get_policy(ntype, dest_id)
        except Exception:
            pass
        data["exclusions"] = {}
        for et in EXCL_TYPES:
            try:
                data["exclusions"][et] = api.get_exclusions(scope, et)
            except Exception:
                pass
        try:
            data["unified_exclusions"] = api.get_unified_exclusions(scope)
        except Exception:
            pass
        try:
            data["restrictions"] = api.get_blocklist(scope)
        except Exception:
            pass
        data["firewall"] = {}
        try:
            data["firewall"]["rules"] = api.get_firewall_rules(scope)
        except Exception:
            pass
        if ntype != "group":
            try:
                data["firewall"]["locations"] = api.get_locations(scope)
            except Exception:
                pass
        data["deviceControl"] = {}
        try:
            data["deviceControl"]["rules"] = \
                api.get_device_control_rules(scope)
        except Exception:
            pass
        data["networkQuarantine"] = {}
        try:
            data["networkQuarantine"]["rules"] = api.get_nq_rules(scope)
        except Exception:
            pass
        if ntype != "group":
            try:
                data["deepVisibility"] = {
                    "filters": api.get_saved_filters(scope)}
            except Exception:
                pass
        try:
            data.setdefault("config", {})["overrides"] = \
                api.get_config_overrides(scope)
        except Exception:
            pass
    return data


# ─── Migration-validation helpers ──────────────────────────────────────
# Reused by ValidationPage to enumerate the scope tree on BOTH consoles
# and explain, in plain English, every difference found between them.

# Human-readable names for the "⏭ Skip <element>" button. During a restore
# the button renames itself to name the step currently running, so the operator
# always knows exactly what a Skip click will jump past. Keys are the internal
# restore step labels; unknown labels fall back to the raw label.
_SKIP_DEFAULT = "⏭  Skip Element"
_SKIP_LABELS = {
    "snapshot": "snapshot",
    "policy": "policy",
    "excl": "exclusions",
    "unified-excl": "unified excl",
    "blocklist": "blocklist",
    "fw-cfg": "FW config",
    "fw-rules": "FW rules",
    "nq-cfg": "NQ config",
    "nq-rules": "NQ rules",
    "dc-cfg": "DC config",
    "dc-rules": "DC rules",
    "tags-fw": "FW tags",
    "tags-nq": "NQ tags",
    "tags-ep": "device tags",
    "ep-tags": "endpoint tags",
    "star": "STAR rules",
    "dv-filters": "saved filters",
    "overrides": "overrides",
    "threat-intel": "threat intel",
    "log-rules": "log rules",
    "upgrade-pol": "upgrade pols",
    "locations": "locations",
    "webhooks": "webhooks",
    "sched-rep": "reports",
    "recipients": "recipients",
    "set-noti": "notifications",
    "set-sysl": "syslog",
    "set-acti": "AD settings",
    "set-smtp": "SMTP",
    "set-sso": "SSO",
}


def _skip_button_text(label: str) -> str:
    """Return the Skip-button caption for the restore step `label`
    (e.g. 'fw-rules' → '⏭  Skip FW rules'). Empty label → the idle default."""
    if not label:
        return _SKIP_DEFAULT
    return f"⏭  Skip {_SKIP_LABELS.get(label, label)}"


# Friendly labels for the categories produced by _summarize_node_payload.
_CAT_LABELS = {
    "policy": "Policy",
    "unified_exclusions": "Unified Exclusions (tag-based)",
    "blocklist": "Blocklist / restrictions",
    "fw-rules": "Firewall rules",
    "fw-locations": "Firewall locations",
    "dc-rules": "Device-control rules",
    "nq-rules": "Network-quarantine rules",
    "saved_filters": "Saved filters (Deep Visibility)",
    "config_overrides": "Config overrides",
    "console_users": "Console users",
    "star_rules": "STAR custom detection rules",
    "threat_intel": "Threat Intel IOCs",
    "tags_firewall": "Tags · firewall",
    "tags_network_quarantine": "Tags · network quarantine",
    "tags_endpoint": "Tags · endpoint",
    "log_collection_rules": "Log collection rules",
    "auto_upgrade_policies": "Auto-upgrade policies",
    "webhooks": "Webhooks",
    "scheduled_reports": "Scheduled reports",
    "roles": "RBAC roles",
    "service_users": "Service users",
    "gateways": "Gateways",
    "marketplace_apps": "Marketplace apps",
    "scripts": "Remote scripts",
    "firewall_config": "Firewall config (present?)",
    "nq_config": "Network-quarantine config (present?)",
    "device_control_config": "Device-control config (present?)",
    "settings_notifications": "Notification settings (present?)",
    "settings_sso": "SSO settings (present?)",
    "settings_smtp": "SMTP settings (present?)",
    "settings_syslog": "Syslog settings (present?)",
    "settings_ad": "AD settings (present?)",
}


def _cat_label(cat: str) -> str:
    if cat in _CAT_LABELS:
        return _CAT_LABELS[cat]
    if cat.startswith("excl/"):
        return f"Exclusions · {cat.split('/', 1)[1]}"
    return cat


def _enumerate_tree(api, filters: dict, levels: dict) -> list:
    """List every scope node (global/account/site/group) on a console,
    honouring the same name filters as backup/restore. Each entry carries
    the names of its ancestors so two consoles can be matched by NAME
    (IDs are tenant-specific and never line up across consoles)."""
    acct_f = filters.get("account") or ""
    site_f = filters.get("site") or ""
    group_f = filters.get("group") or ""

    out = []
    if levels.get("global"):
        out.append({"type": "global", "path": "/", "name": "global",
                    "id": "", "account_name": "", "site_name": ""})
    try:
        accounts = api.get_accounts()
    except Exception as e:
        accounts = []
        cli_log(f"Could not list accounts: {e}", "error")
    for acct in _select_by_name(accounts, acct_f,
                                key=lambda a: a.get("name", "?")):
        aname = acct.get("name", "?")
        aid = acct.get("id", "")
        if levels.get("accounts"):
            out.append({"type": "account", "path": f"{aname}/",
                        "name": aname, "id": aid,
                        "account_name": aname, "site_name": ""})
        if not (levels.get("sites") or levels.get("groups")):
            continue
        try:
            sites = api.get_sites(params={
                "accountIds": aid, "sortBy": "name", "sortOrder": "asc"})
        except Exception as e:
            sites = []
            cli_log(f"Could not list sites under {aname}: {e}", "warning")
        for site in _select_by_name(sites, site_f,
                                     key=lambda s: s.get("name", "?")):
            sname = site.get("name", "?")
            sid = site.get("id", "")
            if levels.get("sites"):
                out.append({"type": "site", "path": f"{aname}/{sname}",
                            "name": sname, "id": sid,
                            "account_name": aname, "site_name": sname})
            if not levels.get("groups"):
                continue
            try:
                groups = api.get_groups(params={
                    "siteIds": sid, "sortBy": "name", "sortOrder": "asc"})
            except Exception as e:
                groups = []
                cli_log(f"Could not list groups under {aname}/{sname}: {e}",
                        "warning")
            for g in _select_by_name(groups, group_f,
                                      key=lambda x: x.get("name", "?")):
                gname = g.get("name", "?")
                gid = g.get("id", "")
                out.append({"type": "group",
                            "path": f"{aname}/{sname}/{gname}",
                            "name": gname, "id": gid,
                            "account_name": aname, "site_name": sname})
    return out


def _explain_diff(cat: str, src: int, dst: int,
                  missing: list, extra: list) -> tuple:
    """Return (headline, why, fix) explaining a single element difference
    in language a non-expert can act on."""
    label = _cat_label(cat)
    miss_s = ", ".join(missing[:5]) + (" …" if len(missing) > 5 else "")
    extra_s = ", ".join(extra[:5]) + (" …" if len(extra) > 5 else "")
    if src and not dst:
        return ("Nothing migrated",
                f"The destination has NONE of the {src} {label} item(s) "
                f"that exist on the source. They were probably excluded "
                f"from the restore, filtered out by scope, or the restore "
                f"of this element failed.",
                "Re-run the Restore for this element at this scope, then "
                "validate again.")
    if missing and not extra:
        return ("Missing on destination",
                f"{len(missing)} {label} item(s) exist on the source but "
                f"are absent on the destination: {miss_s}.",
                "Re-run the Restore for these item(s), or confirm they were "
                "intentionally skipped.")
    if extra and not missing:
        inherit_note = ""
        if cat in ("fw-rules", "dc-rules", "nq-rules"):
            inherit_note = (" For rules, extra items are often inherited "
                            "from a parent scope (account/site) and are "
                            "expected.")
        return ("Extra on destination",
                f"The destination has {len(extra)} {label} item(s) that the "
                f"source does not: {extra_s}.{inherit_note}",
                "Usually safe — these pre-existed on the destination, were "
                "added manually, or are inherited from a parent scope. "
                "Delete them only if the destination must mirror the source "
                "exactly.")
    if missing and extra:
        return ("Items differ",
                f"{len(missing)} item(s) missing ({miss_s}) and "
                f"{len(extra)} extra ({extra_s}). The items may have been "
                f"renamed during migration, or it's a mix of failed and "
                f"pre-existing items.",
                "Compare the names, then re-run the Restore for the missing "
                "item(s).")
    # Same names but different counts (rare — duplicate names).
    return ("Count differs",
            f"Source has {src} {label} item(s), destination has {dst}, "
            f"but the names overlap — likely duplicate names on one side.",
            "Open both consoles and reconcile the duplicates manually.")


# ═══════════════════════════════════════════════════════════════════════
#  Backup Page
# ═══════════════════════════════════════════════════════════════════════

class BackupPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        ctk.CTkLabel(hdr, text="Backup from",
                     font=(UI_FONT, 22, "bold")).pack(side="left")
        self._console_var = ctk.StringVar(value="SOURCE")
        ctk.CTkOptionMenu(hdr, values=["SOURCE", "DESTINATION"],
                          variable=self._console_var, width=160, height=32,
                          font=(UI_FONT, 14, "bold"),
                          command=lambda _: self._update_indicator()).pack(
            side="left", padx=(8, 0))
        self._indicator = ctk.CTkLabel(hdr, text="",
                                       font=(UI_FONT, 11),
                                       text_color=GREEN)
        self._indicator.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(self,
                     text="Reads accounts → sites → groups and saves config to a JSON file.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # options card
        opts = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        opts.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts, text="Levels:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        lv_frame = ctk.CTkFrame(opts, fg_color="transparent")
        lv_frame.grid(row=0, column=1, padx=12, pady=8, sticky="w")
        self.level_vars = {}
        for lv in ["global", "accounts", "sites", "groups"]:
            var = ctk.BooleanVar(value=(lv != "global"))
            ctk.CTkCheckBox(lv_frame, text=lv.capitalize(), variable=var,
                            font=(UI_FONT, 12)).pack(side="left", padx=8)
            self.level_vars[lv] = var
        self.level_vars["global"].trace_add(
            "write", lambda *a: self._toggle_global_mode())

        # scope filters (hidden when Global is checked)
        self._scope_widgets = []
        for row_i, (lbl_text, ph, attr) in enumerate([
            ("Account Name:", "(blank = all accounts)", "acct_filter"),
            ("Site Name:", "(blank = all sites)", "site_filter"),
            ("Group Name:", "(blank = all groups)", "group_filter"),
        ], start=1):
            lbl = ctk.CTkLabel(opts, text=lbl_text,
                               font=(UI_FONT, 13))
            lbl.grid(row=row_i, column=0, padx=12, pady=6, sticky="w")
            entry = ctk.CTkEntry(opts, placeholder_text=ph, height=32)
            entry.grid(row=row_i, column=1, padx=12, pady=6, sticky="ew")
            setattr(self, attr, entry)
            self._scope_widgets.extend([lbl, entry])

        self._elem_hdr, self.elem_vars = _build_elements_section(
            opts, row=4, title="Backup Elements")
        self._scope_widgets.append(self._elem_hdr)

        # buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=20, pady=8)
        self._start_btn = ctk.CTkButton(
            btn_row, text="▶ Start Backup", height=38,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            font=(UI_FONT, 14, "bold"),
            command=self._start)
        self._start_btn.pack(side="left", padx=(0, 4))
        self._stop_btn = ctk.CTkButton(
            btn_row, text="■ Stop", height=38, width=80,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=(UI_FONT, 13, "bold"),
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Export Log", height=38,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_row, text="📜 History", height=38,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._show_history).pack(side="left", padx=(0, 4))
        self._star_btn = ctk.CTkButton(
            btn_row, text="⭐ STAR → Excel", height=38, width=150,
            fg_color=BRAND, hover_color=BRAND_HOVER,
            command=self._export_star_rules)
        self._star_btn.pack(side="left", padx=(0, 2))
        _help_btn(btn_row,
                  "Export every STAR custom detection rule from the selected "
                  "console straight to a detailed Excel workbook — all fields, "
                  "colour-coded by scope / status / severity, with a summary "
                  "sheet and filters already switched on.\n\n"
                  "Honours the Account Name / Site Name filters above. No "
                  "backup needed — it reads the console live."
                  ).pack(side="left", padx=(0, 4))

        # ── Scheduled (unattended) backups — fires while the app is open ──
        ctk.CTkLabel(btn_row, text="⏰", font=(UI_FONT, 14)).pack(
            side="left", padx=(8, 0))
        self._sched_var = ctk.StringVar(value="Off")
        self._sched_menu = ctk.CTkOptionMenu(
            btn_row, variable=self._sched_var, width=120, height=38,
            values=["Off", "Hourly", "Every 6h", "Every 12h", "Daily"],
            command=lambda _v: self._on_schedule_change())
        self._sched_menu.pack(side="left", padx=(2, 4))
        _help_btn(btn_row,
                  "Run this backup automatically on a cadence (while the app "
                  "is open) using the current console + scope + element "
                  "selection. Files land in ~/.s1-command-center/"
                  "scheduled-backups/. For true unattended backups when the "
                  "app is closed, use an OS scheduler."
                  ).pack(side="left", padx=(0, 4))

        # ── Migration profiles (reusable scope + element selections) ──
        prof_box = ctk.CTkFrame(btn_row, fg_color="transparent")
        prof_box.pack(side="right")
        ctk.CTkLabel(prof_box, text="Profile:",
                     font=(UI_FONT, 12)).pack(side="left", padx=(0, 4))
        self._profile_var = ctk.StringVar(value="—")
        self._profile_menu = ctk.CTkOptionMenu(
            prof_box, variable=self._profile_var, width=150, height=32,
            values=["—"], font=(UI_FONT, 12))
        self._profile_menu.pack(side="left", padx=2)
        ctk.CTkButton(prof_box, text="Load", height=32, width=56,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._load_profile).pack(side="left", padx=2)
        ctk.CTkButton(prof_box, text="Save", height=32, width=56,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._save_profile).pack(side="left", padx=2)
        ctk.CTkButton(prof_box, text="🗑", height=32, width=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._delete_profile).pack(side="left", padx=2)

        self.progress = ctk.CTkProgressBar(btn_row, width=200)
        self.progress.pack(side="left", padx=8)
        self.progress.set(0)
        self._timer_lbl = ctk.CTkLabel(btn_row, text="",
                                        font=(MONO_FONT, 12),
                                        text_color=TEXT_MUTED)
        self._timer_lbl.pack(side="left", padx=(8, 0))
        self._status_lbl = ctk.CTkLabel(btn_row, text="",
                                         font=(UI_FONT, 12, "bold"),
                                         text_color=TEXT_MUTED)
        self._status_lbl.pack(side="left", padx=(8, 0))

        # progress table
        self.grid_rowconfigure(4, weight=1)
        self.ptable = ProgressTable(self, height=300)
        self.ptable.grid(row=4, column=0, sticky="nsew", padx=20, pady=(4, 12))

        self.log = _ConsoleProxy(self.app)
        self._timer_running = False
        self._timer_start = 0.0
        self._operation_log = []
        self._cancelled = False
        self._skip_element = False
        self._acct_id = ""  # set by JiraPage._load_ticket for ID-based validation
        self._sched_after_id = None
        self._refresh_profiles()
        self._load_schedule()

    def _show_history(self):
        """Print recent tool operations (audit history) to the console log."""
        entries = self.app.audit.recent(limit=25)
        if not entries:
            cli_log("No operation history yet.", "info")
            return
        cli_log(f"📜 Operation history (last {len(entries)}):", "cmd")
        for e in entries:
            when = (e.get("when") or "")[:19].replace("T", " ")
            action = (e.get("action") or "?").upper()
            extra = " ".join(
                f"{k}={v}" for k, v in e.items()
                if k not in ("when", "action") and v not in (None, ""))
            cli_log(f"  {when}  {action:<9} {extra}", "info")

    # ── Scheduled backups ─────────────────────────────────────────────────
    _SCHED_MINUTES = {"Off": 0, "Hourly": 60, "Every 6h": 360,
                      "Every 12h": 720, "Daily": 1440}

    def _schedule_file(self):
        d = os.path.join(os.path.expanduser("~"), ".s1-command-center")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "schedule.json")

    def _load_schedule(self):
        try:
            with open(self._schedule_file()) as f:
                val = (json.load(f) or {}).get("interval", "Off")
            if val in self._SCHED_MINUTES:
                self._sched_var.set(val)
                self._arm_schedule()
        except Exception:
            pass

    def _on_schedule_change(self):
        try:
            with open(self._schedule_file(), "w") as f:
                json.dump({"interval": self._sched_var.get()}, f)
        except Exception:
            pass
        self._arm_schedule()
        choice = self._sched_var.get()
        cli_log(f"⏰ Scheduled backup: {choice}"
                + ("" if choice == "Off" else " (while the app is open)"),
                "info")

    def _arm_schedule(self):
        # Cancel any pending tick, then (re)arm if enabled.
        old = getattr(self, "_sched_after_id", None)
        if old is not None:
            try:
                self.after_cancel(old)
            except Exception:
                pass
            self._sched_after_id = None
        minutes = self._SCHED_MINUTES.get(self._sched_var.get(), 0)
        if minutes > 0:
            self._sched_after_id = self.after(
                minutes * 60 * 1000, self._scheduled_tick)

    def _scheduled_tick(self):
        self._sched_after_id = None
        try:
            self._run_scheduled_backup()
        finally:
            self._arm_schedule()  # re-arm for the next interval

    def _run_scheduled_backup(self):
        if self._timer_running:
            cli_log("⏰ Scheduled backup skipped — a backup is already "
                    "running.", "warning")
            return
        api = self.app.source_api
        if not api:
            cli_log("⏰ Scheduled backup skipped — SOURCE not connected.",
                    "warning")
            return
        levels = {k: v.get() for k, v in self.level_vars.items()}
        elements = [k for k, v in self.elem_vars.items() if v.get()]
        if not elements:
            cli_log("⏰ Scheduled backup skipped — no elements selected.",
                    "warning")
            return
        filters = {
            "account": self.acct_filter.get().strip(),
            "site": self.site_filter.get().strip(),
            "group": self.group_filter.get().strip(),
        }
        folder = os.path.join(os.path.expanduser("~"), ".s1-command-center",
                              "scheduled-backups")
        os.makedirs(folder, exist_ok=True)
        host = (getattr(api, "base_url", "src") or "src")
        host = host.replace("https://", "").replace("http://", "").split("/")[0]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(folder, f"scheduled-{host}-{ts}.json")
        import time as _time
        self.ptable.clear()
        self._operation_log = []
        self._cancelled = False
        self.progress.set(0)
        self._timer_start = _time.time()
        self._timer_running = True
        self._tick_timer()
        self._set_ui_running(True)
        cli_log(f"⏰ Scheduled backup starting → {os.path.basename(path)}",
                "cmd")

        def do():
            return self._run_backup(api, levels, elements, filters)

        def done(backup_data):
            self._timer_running = False
            self._set_ui_running(False)
            try:
                with open(path, "w") as f:
                    json.dump(backup_data, f, indent=2, default=str)
                os.chmod(path, 0o600)
            except Exception as e:
                cli_log(f"⏰ Scheduled backup save failed: {e}", "error")
                return
            self.progress.set(1)
            cli_log(f"⏰ Scheduled backup saved → {os.path.basename(path)} "
                    f"({len(backup_data)} nodes)", "success")
            self.app.log_audit(
                "scheduled_backup", url=getattr(api, "base_url", ""),
                nodes=len(backup_data), elements=len(elements),
                file=os.path.basename(path))
            # Retention: keep the newest 20 scheduled backups, prune the rest.
            try:
                from migtools import select_backups_to_prune
                entries = [
                    (os.path.join(folder, f), os.path.getmtime(
                        os.path.join(folder, f)))
                    for f in os.listdir(folder)
                    if f.startswith("scheduled-") and f.endswith(".json")]
                for old in select_backups_to_prune(entries, keep_last=20):
                    os.remove(old)
                    cli_log(f"⏰ Pruned old scheduled backup "
                            f"{os.path.basename(old)}", "info")
            except Exception as _e:
                cli_log(f"⏰ Retention prune skipped: {_e}", "warning")

        def fail(e):
            self._timer_running = False
            self._set_ui_running(False)
            cli_log(f"⏰ Scheduled backup failed: {e}", "error")

        run_async(self, do, done, fail)

    # ── Migration profiles ────────────────────────────────────────────────
    def _refresh_profiles(self, select: str = None):
        names = self.app.profiles.names()
        self._profile_menu.configure(values=names or ["—"])
        if select and select in names:
            self._profile_var.set(select)
        elif self._profile_var.get() not in names:
            self._profile_var.set(names[0] if names else "—")

    def _current_selection(self):
        """Snapshot the current scope + element choices for a profile."""
        levels = {k: v.get() for k, v in self.level_vars.items()}
        elements = [k for k, v in self.elem_vars.items() if v.get()]
        filters = {
            "account": self.acct_filter.get().strip(),
            "site": self.site_filter.get().strip(),
            "group": self.group_filter.get().strip(),
        }
        return levels, elements, filters

    def _save_profile(self):
        dlg = ctk.CTkInputDialog(
            text="Profile name (re-saving an existing name overwrites it):",
            title="Save Migration Profile")
        name = (dlg.get_input() or "").strip()
        if not name:
            return
        levels, elements, filters = self._current_selection()
        if not elements:
            messagebox.showwarning(
                "Nothing selected",
                "Select at least one element before saving a profile.")
            return
        self.app.profiles.upsert(
            name, elements=elements, levels=levels, filters=filters,
            created_at=datetime.now(timezone.utc).isoformat())
        self._refresh_profiles(select=name)
        cli_log(f"Saved migration profile '{name}' "
                f"({len(elements)} element(s)).", "success")

    def _load_profile(self):
        name = self._profile_var.get()
        prof = self.app.profiles.get(name) if name and name != "—" else None
        if not prof:
            cli_log("No profile selected to load.", "warning")
            return
        # Levels (default missing keys to False).
        for k, var in self.level_vars.items():
            var.set(bool(prof.levels.get(k, False)))
        # Filters.
        for attr, key in (("acct_filter", "account"),
                          ("site_filter", "site"),
                          ("group_filter", "group")):
            entry = getattr(self, attr)
            entry.delete(0, "end")
            entry.insert(0, prof.filters.get(key, "") or "")
        # Elements — tick exactly the profile's set.
        wanted = set(prof.elements or [])
        for k, var in self.elem_vars.items():
            var.set(k in wanted)
        # Refresh the collapsible header count + global show/hide state.
        self._toggle_global_mode()
        cli_log(f"Loaded migration profile '{name}' "
                f"({len(wanted)} element(s)).", "success")

    def _delete_profile(self):
        name = self._profile_var.get()
        if not name or name == "—":
            return
        if not messagebox.askyesno(
                "Delete Profile", f"Delete migration profile '{name}'?"):
            return
        self.app.profiles.remove(name)
        self._refresh_profiles()
        cli_log(f"Deleted migration profile '{name}'.", "info")

    def _tick_timer(self):
        if not self._timer_running:
            return
        import time
        elapsed = time.time() - self._timer_start
        m, s = divmod(int(elapsed), 60)
        self._timer_lbl.configure(text=f"{m:02d}:{s:02d}")
        self.after(500, self._tick_timer)

    def _toggle_global_mode(self):
        """When Global is checked, hide scope filters and elements
        (will backup everything). When unchecked, show them."""
        is_global = self.level_vars["global"].get()
        for w in self._scope_widgets:
            if is_global:
                w.grid_remove()
            else:
                w.grid()

    def _update_indicator(self):
        choice = self._console_var.get()
        if choice == "SOURCE":
            ctx = self.app.cfg.get_by_role("source")
            color = GREEN
            self.app.set_active_console("source")
        else:
            ctx = self.app.cfg.get_by_role("destination")
            color = ACCENT
            self.app.set_active_console("destination")
        if ctx:
            self._indicator.configure(
                text=f"▶ {ctx.name}  ({ctx.display_url})", text_color=color)
        else:
            self._indicator.configure(
                text=f"▶ {choice} — not connected", text_color=TEXT_MUTED)

    def on_show(self):
        self._update_indicator()

    def _get_backup_api(self):
        """Return the API for the selected console, with a warning if non-default."""
        choice = self._console_var.get()
        if choice == "SOURCE":
            api = self.app.source_api
            if not api:
                cli_log("No SOURCE console connected.", "error")
                return None
            return api
        else:
            api = self.app.dest_api
            if not api:
                cli_log("No DESTINATION console connected.", "error")
                return None
            if not messagebox.askyesno(
                    "Non-standard direction",
                    "You are about to BACKUP from the DESTINATION console.\n"
                    "Normally backups are taken from SOURCE.\n\n"
                    "Are you sure you want to continue?"):
                return None
            return api

    def _stop(self):
        self._cancelled = True
        self._stop_btn.configure(state="disabled")
        self._status_lbl.configure(text="Stopping…", text_color=WARN)
        cli_log("Backup stop requested — finishing current node…", "warning")

    def _set_ui_running(self, running: bool):
        # Lock the rest of the app while a backup runs — only Stop (and the
        # OUTPUT drawer) stay clickable, so nothing disturbs the running job.
        self.app.set_busy(running, allow=(self._start_btn, self._stop_btn))
        if running:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._status_lbl.configure(text="Backup running…",
                                        text_color=INFO)
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")

    def _start(self):
        api = self._get_backup_api()
        if not api:
            return

        levels = {k: v.get() for k, v in self.level_vars.items()}
        if levels.get("global"):
            if not messagebox.askyesno(
                    "⚠️ Global Backup",
                    "Global is checked — this will backup the ENTIRE console's "
                    "global-level configuration.\n\n"
                    "Are you sure you want to include Global?"):
                return

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Save backup as",
            initialfile=f"s1-backup-{datetime.now():%Y%m%d-%H%M}.json")
        if not path:
            return

        elements = [k for k, v in self.elem_vars.items() if v.get()]
        filters = {
            "account": self.acct_filter.get().strip(),
            "site": self.site_filter.get().strip(),
            "group": self.group_filter.get().strip(),
        }
        import time as _time
        self.ptable.clear()
        self._operation_log = []
        self._cancelled = False
        self.progress.set(0)
        self._timer_start = _time.time()
        self._timer_running = True
        self._tick_timer()
        self._set_ui_running(True)
        cli_log(f"Starting backup from {self._console_var.get()} console…", "cmd")

        def do():
            return self._run_backup(api, levels, elements, filters)

        def done(backup_data):
            import time as _t
            self._timer_running = False
            self._set_ui_running(False)
            elapsed = _t.time() - self._timer_start
            m, s = divmod(int(elapsed), 60)
            if self._cancelled:
                self._timer_lbl.configure(
                    text=f"⊘ {m:02d}:{s:02d}", text_color=WARN)
                self._status_lbl.configure(
                    text=f"Stopped — {len(backup_data)} nodes saved",
                    text_color=WARN)
            elif len(backup_data) == 0:
                self._timer_lbl.configure(
                    text=f"⚠ {m:02d}:{s:02d}", text_color=WARN)
                self._status_lbl.configure(
                    text="0 nodes — check connection & filters",
                    text_color=WARN)
            else:
                self._timer_lbl.configure(
                    text=f"✓ {m:02d}:{s:02d}", text_color=GREEN)
                self._status_lbl.configure(
                    text=f"Done — {len(backup_data)} nodes",
                    text_color=GREEN)
            if len(backup_data) == 0:
                self.progress.set(0)
                cli_log("Backup returned 0 nodes — nothing was saved. "
                        "Check your connection and filters.", "warning")
                return
            with open(path, "w") as f:
                json.dump(backup_data, f, indent=2, default=str)
            # Backup contains sensitive config (SSO/SMTP/Syslog/AD) — restrict it.
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            self.app._last_backup_path = path  # share with Restore page
            self._operation_log.append(
                f"Backup saved to {path} ({len(backup_data)} nodes, "
                f"{m}m {s}s)")
            self.progress.set(1)
            self.app.set_status(f"Backup complete → {path}")
            cli_log(f"Backup: {len(backup_data)} nodes in {m}m {s}s → {os.path.basename(path)}", "success")
            self.app.log_audit(
                "backup", console=self._console_var.get(),
                url=getattr(api, "base_url", ""), nodes=len(backup_data),
                elements=len(elements), file=os.path.basename(path))

        def fail(e):
            self._timer_running = False
            self._set_ui_running(False)
            self._timer_lbl.configure(text="✗ failed", text_color=ACCENT)
            self._status_lbl.configure(text=f"Error: {str(e)[:40]}",
                                        text_color=ACCENT)
            cli_log(f"Backup failed: {e}", "error")
            self.progress.set(0)

        run_async(self, do, done, fail)

    def _run_backup(self, api, levels, elements, filters):
        # ── verify connection first ──
        try:
            api.get_my_user()
        except S1APIError as e:
            if e.status_code == 401:
                raise S1APIError("Connection refused — invalid or expired API token.", 401)
            short = e.message[:80] if len(e.message) > 80 else e.message
            raise S1APIError(f"Cannot reach console — {short}", e.status_code)
        except Exception:
            raise S1APIError(f"Cannot reach console — connection refused. Check URL and token.")

        nodes = []
        acct_f    = filters.get("account", "")
        site_f    = filters.get("site", "")
        group_f   = filters.get("group", "")
        acct_id_f = getattr(self, "_acct_id", "").strip()
        pt = self.ptable

        def ui(fn):
            self.after(0, fn)

        def _acct_selected(acct):
            return str(acct.get("id", "")) in _selected_acct_ids

        def _make_summary(results):
            """Build compact summary from _read_node results."""
            parts = []
            for name, val in results:
                if val == "n/a" or val == 0:
                    continue
                elif val == "ok":
                    parts.append(name)
                elif val == "ERR":
                    pass
                elif isinstance(val, int) and val > 0:
                    parts.append(f"{name}:{val}")
            return ", ".join(parts) if parts else "empty"

        def _backup_node(nid, scope_type, scope_id, scope):
            """Backup a single node, update table."""
            ui(lambda: pt.set_running(nid))
            data = self._read_node(api, scope_type, scope_id, scope,
                                   elements, lambda msg: None)
            # build summary from last _read_node results
            summary = _make_summary(self._last_results)
            ui(lambda: pt.set_done(nid, summary))
            return data

        # ── global ──
        if levels.get("global"):
            nid = "global"
            ui(lambda: pt.add_node(nid, "/", "global"))
            ui(lambda: pt.set_running(nid))
            scope = _scope("global", "")
            node = {"path": "/", "type": "global", "systemConfig": {},
                    "data": self._read_node(api, "global", "", scope,
                                            elements, lambda m: None)}
            summary = _make_summary(self._last_results)
            ui(lambda: pt.set_done(nid, summary))
            try:
                user_info = api.get_my_user()
                sys_info = {}
                try: sys_info = api.get_system_info()
                except Exception: pass
                node["backupMetadata"] = {
                    "backupVersion": "gui-1.0",
                    "systemInformation": sys_info,
                    "url": api.base_url,
                    "scope": {"filters": filters, "levels": levels},
                    "start": datetime.now(timezone.utc).isoformat(),
                    "runByUser": user_info,
                    "restoreToContext": "",
                }
            except Exception as e:
                cli_log(f"Backup metadata (user/system info) unavailable: {e}",
                        "warning")
            nodes.append(node)

        # ── discover structure ──
        accounts = api.get_accounts()
        id_match = []
        if acct_id_f:
            id_match = [a for a in accounts if str(a.get("id", "")) == acct_id_f]
            if not id_match:
                cli_log(f"⚠ Backup account ID {acct_id_f} not found — "
                        f"falling back to Account Name filter", "warning")
            else:
                cli_log(f"  ✓ Backup: account ID {acct_id_f} → "
                        f"'{id_match[0].get('name')}' confirmed", "success")
        if id_match:
            _selected_acct_ids = {str(a.get("id", "")) for a in id_match}
        else:
            _selected_acct_ids = {
                str(a.get("id", "")) for a in _select_by_name(
                    accounts, acct_f, key=lambda a: a.get("name", ""))}
        matched_accounts = [a for a in accounts if _acct_selected(a)]
        if acct_f and not matched_accounts:
            names = ", ".join(str(a.get("name", "?")) for a in accounts[:10])
            more = f" (+{len(accounts) - 10} more)" if len(accounts) > 10 else ""
            cli_log(f"No source account matched '{filters.get('account', '')}' "
                    f"on {api.base_url}. Visible API accounts: {names}{more}. "
                    f"Check the selected SOURCE connection and token scope.",
                    "warning")
        node_count = 0
        for acct in accounts:
            aname = acct.get("name", "?")
            aid = acct.get("id", "")
            if not _acct_selected(acct):
                continue
            node_count += 1
            try:
                sites = api.get_sites(params={
                    "accountIds": aid, "states": "active",
                    "sortBy": "name", "sortOrder": "asc"})
                if not sites:
                    sites = api.get_sites(params={
                        "accountIds": aid,
                        "sortBy": "name", "sortOrder": "asc"})
            except Exception:
                sites = []
            for site in _select_by_name(sites, site_f,
                                         key=lambda s: s.get("name", "")):
                sname = site.get("name", "?")
                sid = site.get("id", "")
                node_count += 1
                try:
                    groups = api.get_groups(params={
                        "siteIds": sid, "sortBy": "name",
                        "sortOrder": "asc"})
                except Exception:
                    groups = []
                node_count += len(_select_by_name(
                    groups, group_f, key=lambda g: g.get("name", "?")))

        # ── add all rows as pending first ──
        row_map = []  # (nid, type, path, obj, scope_id)
        idx = 0
        for acct in accounts:
            aname = acct.get("name", "?")
            aid = acct.get("id", "")
            if not _acct_selected(acct):
                continue
            nid = f"acct-{aid}"
            ui(lambda n=nid, p=f"{aname}/": pt.add_node(n, p, "account"))
            row_map.append((nid, "account", f"{aname}/", acct, aid))

            try:
                sites = api.get_sites(params={
                    "accountIds": aid, "states": "active",
                    "sortBy": "name", "sortOrder": "asc"})
                if not sites:
                    sites = api.get_sites(params={
                        "accountIds": aid,
                        "sortBy": "name", "sortOrder": "asc"})
            except Exception:
                sites = []

            for site in _select_by_name(sites, site_f,
                                         key=lambda s: s.get("name", "")):
                sname = site.get("name", "?")
                sid = site.get("id", "")
                nid = f"site-{sid}"
                sp = f"{aname}/{sname}"
                ui(lambda n=nid, p=sp: pt.add_node(n, p, "site"))
                row_map.append((nid, "site", sp, site, sid))

                try:
                    groups = api.get_groups(params={
                        "siteIds": sid, "sortBy": "name",
                        "sortOrder": "asc"})
                except Exception:
                    groups = []
                # Enrich dynamic-group payloads with the saved filter's
                # NAME (resolved from the source console) so restore can
                # map it to the destination filter by name. Some S1
                # versions don't include `filterName` in /groups responses.
                _src_filter_name_by_id: dict = {}
                for grp in _select_by_name(groups, group_f,
                                            key=lambda g: g.get("name", "?")):
                    gname = grp.get("name", "?")
                    gid = grp.get("id", "")
                    fid = (grp.get("filterId")
                           or (grp.get("filter") or {}).get("id"))
                    if fid and not grp.get("filterName"):
                        fname = _src_filter_name_by_id.get(str(fid))
                        if fname is None:
                            try:
                                hits = api.get_saved_filters(
                                    {"ids": str(fid)})
                                fname = (hits[0].get("name")
                                         if hits else "")
                            except Exception:
                                fname = ""
                            _src_filter_name_by_id[str(fid)] = fname or ""
                        if fname:
                            grp["filterName"] = fname
                    nid = f"grp-{gid}"
                    gp = f"{aname}/{sname}/{gname}"
                    ui(lambda n=nid, p=gp: pt.add_node(n, p, "group"))
                    row_map.append((nid, "group", gp, grp, gid))

        # ── process each node ──
        import time as _time
        _time.sleep(0.1)  # let UI render pending rows
        for i, (nid, ntype, npath, obj, sid) in enumerate(row_map):
            # check for cancellation
            if self._cancelled:
                for j in range(i, len(row_map)):
                    ui(lambda n=row_map[j][0]: pt.set_skipped(n, "cancelled"))
                self._operation_log.append("— Backup cancelled by user —")
                break

            ui(lambda v=(i+1)/max(len(row_map), 1):
               self.progress.set(v * 0.95))

            level_map = {"account": "accounts", "site": "sites",
                         "group": "groups"}
            if not levels.get(level_map.get(ntype, "")):
                ui(lambda n=nid: pt.set_skipped(n, "level unchecked"))
                continue

            ui(lambda n=nid: pt.set_running(n))
            scope = _scope(ntype, sid)
            try:
                data = self._read_node(api, ntype, sid, scope,
                                       elements, lambda m: None)
                summary = _make_summary(self._last_results)
                pol = data.get("policy", {})
                broken = pol.get("inheritedFrom") is None if pol else False
                node_dict = {"path": npath, "type": ntype,
                             ntype: obj,
                             "policyInheritanceBroken": broken,
                             "data": data}
                nodes.append(node_dict)
                ui(lambda n=nid, s=summary: pt.set_done(n, s))
                # detailed log
                self._operation_log.append(
                    f"[{ntype.upper()}] {npath} — {summary}")
                for rname, rval in self._last_results:
                    self._operation_log.append(
                        f"  {rname}: {rval}")
            except Exception as exc:
                e_msg = str(exc)[:60]
                ui(lambda n=nid, m=e_msg: pt.set_error(n, m))
                self._operation_log.append(
                    f"[{ntype.upper()}] {npath} — ERROR: {e_msg}")

        ui(lambda: self.progress.set(0.98))
        return nodes

    def _read_node(self, api, scope_type, scope_id, scope, elements, log):
        """Fetch all selected config elements for a single scope node.
        Logs one compact line per element: ✓ name(count) or ✗ name."""
        data = {}
        p = "      "
        results = []  # collect (name, count_or_error) for summary

        def _fetch(key, label, fn, *a, store_path=None, **kw):
            """Helper: call fn, store result, track summary."""
            try:
                result = fn(*a, **kw)
                if store_path:
                    obj = data
                    for part in store_path[:-1]:
                        obj = obj.setdefault(part, {})
                    obj[store_path[-1]] = result
                else:
                    data[key] = result
                n = len(result) if isinstance(result, list) else "ok"
                results.append((label, n))
                return result
            except Exception as e:
                sc = getattr(e, "status_code", 0)
                if sc in (403, 404):
                    results.append((label, "n/a"))
                else:
                    results.append((label, f"ERR"))
                    cli_log(f"Backup of {label} failed: {e}", "error")
                return None

        # ── Core ──
        if "policy" in elements:
            try:
                data["policy"] = api.get_policy(scope_type, scope_id)
                results.append(("policy", "ok"))
            except Exception as e:
                results.append(("policy", "ERR"))
                cli_log(f"Backup of policy failed: {e}", "error")

        if "exclusions" in elements:
            data["exclusions"] = {}
            total = 0
            for et in EXCL_TYPES:
                try:
                    items = api.get_exclusions(scope, et)
                    data["exclusions"][et] = items
                    total += len(items)
                except Exception as e:
                    cli_log(f"Backup of exclusions/{et} failed: {e}", "warning")
            results.append(("exclusions", total))

        if "unified_exclusions" in elements:
            try:
                items = api.get_unified_exclusions(scope)
                data["unified_exclusions"] = items
                results.append(("unified_exclusions", len(items)))
            except Exception as e:
                results.append(("unified_exclusions", "ERR"))
                cli_log(f"Backup of unified_exclusions failed: {e}", "error")

        if "blocklist" in elements:
            _fetch("restrictions", "blocklist", api.get_blocklist, scope)

        # ── Firewall ──
        if "firewall_rules" in elements or "firewall_config" in elements:
            data["firewall"] = {}
            if "firewall_config" in elements:
                _fetch(None, "fw-config", api.get_firewall_config, scope,
                       store_path=["firewall", "config"])
            if "firewall_rules" in elements:
                _fetch(None, "fw-rules", api.get_firewall_rules, scope,
                       store_path=["firewall", "rules"])
            _fetch(None, "fw-locations", api.get_locations, scope,
                   store_path=["firewall", "locations"])

        # ── Network Quarantine ──
        if "nq_config" in elements or "nq_rules" in elements:
            data["networkQuarantine"] = {}
            if "nq_config" in elements:
                _fetch(None, "nq-config", api.get_nq_config, scope,
                       store_path=["networkQuarantine", "config"])
            if "nq_rules" in elements:
                _fetch(None, "nq-rules", api.get_nq_rules, scope,
                       store_path=["networkQuarantine", "rules"])

        # ── Device Control ──
        if "device_control_rules" in elements or "device_control_config" in elements:
            data["deviceControl"] = {}
            if "device_control_config" in elements:
                _fetch(None, "dc-config", api.get_device_control_config, scope,
                       store_path=["deviceControl", "config"])
            if "device_control_rules" in elements:
                _fetch(None, "dc-rules", api.get_device_control_rules, scope,
                       store_path=["deviceControl", "rules"])

        # ── Saved filters / DV ──
        if "saved_filters" in elements and scope_type != "group":
            r = _fetch(None, "dv-filters", api.get_saved_filters, scope,
                       store_path=["deepVisibility", "filters"])

        # ── Tags ──
        data.setdefault("config", {})
        data["config"]["tags"] = {}
        if "tags_firewall" in elements:
            _fetch(None, "tags-fw", api.get_tags, "firewall", scope,
                   store_path=["config", "tags", "firewall"])
        if "tags_network_quarantine" in elements:
            _fetch(None, "tags-nq", api.get_tags, "network-quarantine", scope,
                   store_path=["config", "tags", "networkQuarantine"])
        if "tags_endpoint" in elements:
            _fetch(None, "tags-ep", api.get_tags, "device-inventory", scope,
                   store_path=["config", "tags", "deviceInventory"])
            _fetch(None, "ep-tags", api.get_endpoint_tags, scope,
                   store_path=["config", "endpointTags"])

        # ── STAR ──
        if "star_rules" in elements and scope_type != "group":
            rules = _fetch("star", "star", api.get_star_rules, scope)
            # /cloud-detection/rules returns INHERITED rules at every level, so
            # an account rule is also returned under each child site. Keep only
            # this node's own-scope rules (except at global, the capture-all
            # scope) so a rule isn't stored — and later re-created — at every
            # site. See _star_rules_for_scope.
            if isinstance(rules, list) and scope_type != "global":
                scoped = _star_rules_for_scope(rules, scope_type)
                data["star"] = scoped
                for _i, (_nm, _v) in enumerate(results):
                    if _nm == "star":
                        results[_i] = ("star", len(scoped))
                        break

        # ── Threat Intel ──
        if "threat_intel" in elements and scope_type == "account":
            _fetch("threatIntel", "threat-intel", api.get_threat_intel,
                   params={"accountIds": scope_id}, max_items=5000)

        # ── Config overrides ──
        if "config_overrides" in elements:
            _fetch(None, "overrides", api.get_config_overrides, scope,
                   store_path=["config", "overrides"])

        # ── Log collection rules ──
        if "log_collection_rules" in elements and scope_type in ("account", "site"):
            _fetch("logCollectionRules", "log-rules",
                   api.get_log_collection_rules, scope)

        # ── Auto-upgrade policies ──
        if "auto_upgrade_policies" in elements and scope_type in ("account", "site"):
            _fetch("autoUpgradePolicies", "upgrade-pol",
                   api.get_auto_upgrade_policies, scope)

        # ── Locations (firewall location-awareness) ──
        if "locations" in elements:
            _fetch("locations", "locations", api.get_locations, scope)

        # ── Webhooks ──
        if "webhooks" in elements and scope_type in ("account", "site", "global"):
            _fetch("webhooks", "webhooks", api.get_webhooks, scope)

        # ── Scheduled reports ──
        if "scheduled_reports" in elements and scope_type in ("account", "site", "global"):
            _fetch("scheduledReports", "sched-rep",
                   api.get_scheduled_reports, scope)

        # ── Marketplace integrations (inventory only) ──
        if "marketplace_apps" in elements and scope_type in ("account", "global"):
            _fetch("marketplaceApps", "mkt-apps",
                   api.get_marketplace_apps, scope)

        # ── Remote Scripts library (inventory only) ──
        if "scripts" in elements and scope_type in ("account", "global"):
            _fetch("scripts", "scripts", api.get_scripts, params=scope)

        # ── Settings ──
        if scope_type in ("account", "site", "global"):
            settings = {}
            smap = [
                ("settings_notifications", "notifications",
                 api.get_notification_settings),
                ("settings_sso", "sso", api.get_sso_settings),
                ("settings_smtp", "smtp", api.get_smtp_settings),
                ("settings_syslog", "syslog", api.get_syslog_settings),
                ("settings_ad", "activeDirectory", api.get_ad_settings),
            ]
            for ekey, sname, getter in smap:
                if ekey in elements:
                    try:
                        settings[sname] = getter(scope)
                        results.append((f"set-{sname[:4]}", "ok"))
                    except Exception as e:
                        results.append((f"set-{sname[:4]}", "n/a"))
                        cli_log(f"Backup of {sname} settings skipped: {e}",
                                "warning")
            if "settings_notifications" in elements:
                try:
                    settings["recipients"] = api.get_notification_recipients(scope)
                except Exception as e:
                    cli_log(f"Backup of notification recipients skipped: {e}",
                            "warning")
            if settings:
                data["settings"] = settings

        # ── RBAC roles ──
        if "roles" in elements and scope_type == "account":
            roles = _fetch("roles", "roles", api.get_roles,
                           params={"accountIds": scope_id})
            for r in (roles or []):
                # Skip predefined roles — they exist on every console and can't
                # be re-created. S1 flags them via `predefined` or the
                # `predefinedRole` boolean depending on the endpoint.
                if not isinstance(r, dict) or r.get("predefined") is True \
                        or r.get("predefinedRole") is True:
                    continue
                rid = r.get("id")
                if not rid:
                    continue
                try:
                    full = api.get_role(rid, params={"accountIds": scope_id})
                    if isinstance(full, dict):
                        r.update(full)
                except Exception as e:
                    cli_log(f"Role definition fetch failed for "
                            f"{r.get('name', rid)}: {e}", "warning")

        # ── Service users ──
        if "service_users" in elements and scope_type == "account":
            _fetch("serviceUsers", "svc-users", api.get_service_users,
                   params={"accountIds": scope_id})

        # ── Console (human) users ──
        if "console_users" in elements and scope_type == "account":
            _fetch("consoleUsers", "users", api.get_users,
                   params={"accountIds": scope_id}, max_items=500)

        # ── Gateways ──
        if "gateways" in elements and scope_type in ("account", "site"):
            _fetch("gateways", "gateways", api.get_gateways, scope)

        # Store results for ProgressTable summary
        self._last_results = results

        return data

    def _export(self):
        if not self._operation_log:
            cli_log("No backup log to export.", "warning")
            return
        rows = [{"log": line} for line in self._operation_log]
        export_report("Backup Log", ["log"], rows)

    def _export_star_rules(self):
        """Read STAR custom detection rules live from the selected console and
        write a detailed, filterable Excel workbook. Independent of a backup —
        it only needs a connection, and honours the Account/Site filters."""
        api = self._get_backup_api()
        if not api:
            return

        acct_f = self.acct_filter.get().strip()
        site_f = self.site_filter.get().strip()
        console = self._console_var.get()

        path = filedialog.asksaveasfilename(
            title="Export STAR Rules to Excel",
            initialfile=f"s1-star-rules-{datetime.now():%Y%m%d-%H%M}",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return

        self._star_btn.configure(state="disabled", text="⏳ Exporting…")
        cli_log("Collecting STAR custom detection rules…", "cmd")

        def do():
            rules = _collect_star_rules(api, acct_f, site_f)
            if not rules:
                return 0
            from export_utils import generate_star_rules_excel
            return generate_star_rules_excel(path, rules, meta={
                "console": getattr(api, "base_url", console),
                "account_filter": acct_f,
                "site_filter": site_f,
            })

        def _reset():
            self._star_btn.configure(state="normal", text="⭐ STAR → Excel")

        def done(count):
            _reset()
            if not count:
                cli_log("No STAR rules matched the current filters.",
                        "warning")
                messagebox.showinfo(
                    "No STAR rules",
                    "No custom detection rules matched the current "
                    "Account/Site filters on this console.")
                return
            cli_log(f"Exported {count} STAR rule(s) → "
                    f"{os.path.basename(path)}", "success")
            messagebox.showinfo(
                "STAR Rules Exported",
                f"{count} custom detection rule(s) written to:\n{path}")

        def fail(exc):
            _reset()
            cli_log(f"STAR export failed: {exc}", "error")
            messagebox.showerror("Export Error", str(exc))

        run_async(self, do, done, fail)


# ═══════════════════════════════════════════════════════════════════════
#  Set Defaults / Edit Properties Dialog
# ═══════════════════════════════════════════════════════════════════════

class SetDefaultsDialog(ctk.CTkToplevel):
    """Dialog to edit isDefault, expiration, unlimitedExpiration,
    and unlimitedLicenses on accounts/sites/groups in a backup JSON."""

    _COLS = [
        ("Type", 60), ("Name", 0), ("Default", 55),
        ("Expiration", 130), ("∞ Exp", 45), ("∞ Lic", 45),
    ]

    def __init__(self, parent, initial_path: Optional[str] = None,
                 on_save: Optional[callable] = None):
        super().__init__(parent)
        self.title("Edit Backup — Defaults & Licenses")
        self.geometry("980x580")
        self.configure(fg_color=CONSOLE_BG)
        self.transient(parent)
        self.grab_set()

        self._entries = []
        self._backup_data = None
        self._file_path = None
        self._row_widgets = []  # per-row widget refs
        self._on_save = on_save

        self._build()
        if initial_path and os.path.isfile(initial_path):
            self._load_file(initial_path)

    # ── UI ─────────────────────────────────────────────────────────────

    def _build(self):
        # file row
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(16, 8))
        self._file_lbl = ctk.CTkLabel(
            top, text="No file loaded", font=(UI_FONT, 12),
            text_color=TEXT_MUTED)
        self._file_lbl.pack(side="left", fill="x", expand=True, anchor="w")
        ctk.CTkButton(top, text="Browse…", width=90, height=30,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      command=self._browse).pack(side="right")

        # filter row
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(filt, text="Show:", font=(UI_FONT, 12)).pack(
            side="left", padx=(0, 6))
        self._filter_var = ctk.StringVar(value="all")
        for val in ["all", "account", "site", "group"]:
            ctk.CTkRadioButton(filt, text=val.capitalize(),
                               variable=self._filter_var, value=val,
                               font=(UI_FONT, 12),
                               command=self._refresh).pack(
                side="left", padx=6)
        self._count_lbl = ctk.CTkLabel(filt, text="", font=(UI_FONT, 11),
                                        text_color=TEXT_MUTED)
        self._count_lbl.pack(side="right")

        # scrollable table
        self._table = ctk.CTkScrollableFrame(
            self, fg_color=CARD, corner_radius=12)
        self._table.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for col, (txt, w) in enumerate(self._COLS):
            kw = {"text": txt, "font": (UI_FONT, 10, "bold"),
                  "text_color": "#888"}
            if w:
                kw["width"] = w
            ctk.CTkLabel(self._table, **kw).grid(
                row=0, column=col, padx=4, pady=4, sticky="w")
        self._table.grid_columnconfigure(1, weight=1)

        # buttons
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(btns, text="∞ Exp ON", height=32, width=90,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      font=(UI_FONT, 11),
                      command=lambda: self._bulk_bool("unlimitedExpiration", True)).pack(
            side="left", padx=(0, 4))
        ctk.CTkButton(btns, text="∞ Exp OFF", height=32, width=90,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      font=(UI_FONT, 11),
                      command=lambda: self._bulk_bool("unlimitedExpiration", False)).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="∞ Lic ON", height=32, width=90,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      font=(UI_FONT, 11),
                      command=lambda: self._bulk_bool("unlimitedLicenses", True)).pack(
            side="left", padx=(0, 4))
        ctk.CTkButton(btns, text="∞ Lic OFF", height=32, width=90,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      font=(UI_FONT, 11),
                      command=lambda: self._bulk_bool("unlimitedLicenses", False)).pack(
            side="left", padx=(0, 4))

        # save row
        save_row = ctk.CTkFrame(self, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(save_row, text="Save to File", height=34,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._save).pack(side="right")
        self._status = ctk.CTkLabel(save_row, text="", font=(UI_FONT, 11),
                                     text_color=TEXT_MUTED)
        self._status.pack(side="right", padx=12)

    # ── Load / Parse ───────────────────────────────────────────────────

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Open backup JSON",
            filetypes=[("JSON", "*.json")])
        if p:
            self._load_file(p)

    def _load_file(self, path: str):
        try:
            with open(path, "r") as f:
                self._backup_data = json.load(f)
            self._file_path = path
            self._file_lbl.configure(
                text=f"File: {os.path.basename(path)}",
                text_color=TEXT)
        except Exception as e:
            self._file_lbl.configure(text=f"Error: {e}", text_color=ACCENT)
            return

        self._entries = []
        for idx, node in enumerate(self._backup_data):
            ntype = node.get("type", "")
            if ntype not in ("account", "site", "group"):
                continue
            obj = node.get(ntype, {}) or {}
            if not isinstance(obj, dict):
                continue
            entry = {
                "idx": idx,
                "type": ntype,
                "name": obj.get("name", node.get("path", "?")),
                "accountName": obj.get("accountName", ""),
            }
            if "isDefault" in obj:
                entry["isDefault"] = bool(obj.get("isDefault"))
            if "expiration" in obj:
                entry["expiration"] = obj.get("expiration") or ""
            if "unlimitedExpiration" in obj:
                entry["unlimitedExpiration"] = bool(obj.get("unlimitedExpiration"))
            if "unlimitedLicenses" in obj:
                entry["unlimitedLicenses"] = bool(obj.get("unlimitedLicenses"))
            # only include if at least one editable field exists
            if any(k in entry for k in ("isDefault", "expiration",
                                         "unlimitedExpiration",
                                         "unlimitedLicenses")):
                self._entries.append(entry)
        self._refresh()

    # ── Table rendering ────────────────────────────────────────────────

    def _refresh(self):
        for w in list(self._table.winfo_children()):
            info = w.grid_info()
            if info and int(info.get("row", 0)) > 0:
                w.destroy()

        filt = self._filter_var.get()
        visible = [e for e in self._entries
                   if filt == "all" or e["type"] == filt]
        self._row_widgets = []

        for i, entry in enumerate(visible, start=1):
            rw = {"entry": entry}

            # col 0 — type
            icons = {"account": "🏢", "site": "🌐", "group": "📁"}
            ctk.CTkLabel(self._table,
                         text=f"{icons.get(entry['type'], '')} {entry['type']}",
                         font=(UI_FONT, 11), width=60).grid(
                row=i, column=0, padx=4, pady=2, sticky="w")

            # col 1 — name
            ctk.CTkLabel(self._table, text=entry["name"],
                         font=(UI_FONT, 12, "bold"),
                         text_color=TEXT).grid(
                row=i, column=1, padx=4, pady=2, sticky="w")

            # col 2 — isDefault checkbox
            if "isDefault" in entry:
                var = ctk.BooleanVar(value=entry["isDefault"])
                var._entry_ref = entry
                cb = ctk.CTkCheckBox(self._table, text="", variable=var,
                                     width=20,
                                     command=lambda v=var:
                                         self._on_toggle(v, "isDefault"))
                cb.grid(row=i, column=2, padx=4, pady=2, sticky="w")
                rw["isDefault"] = var
            else:
                ctk.CTkLabel(self._table, text="—", text_color=TEXT_FAINT,
                             width=55).grid(
                    row=i, column=2, padx=4, pady=2, sticky="w")

            # col 3 — expiration entry
            if "expiration" in entry:
                exp_e = ctk.CTkEntry(self._table, width=130, height=26,
                                     font=(MONO_FONT, 11))
                exp_e.insert(0, entry.get("expiration", ""))
                exp_e.grid(row=i, column=3, padx=4, pady=2, sticky="w")
                exp_e._entry_ref = entry
                exp_e.bind("<FocusOut>", lambda e, w=exp_e:
                           self._on_exp_change(w))
                rw["expiration"] = exp_e
            else:
                ctk.CTkLabel(self._table, text="—", text_color=TEXT_FAINT,
                             width=130).grid(
                    row=i, column=3, padx=4, pady=2, sticky="w")

            # col 4 — unlimitedExpiration checkbox
            if "unlimitedExpiration" in entry:
                var2 = ctk.BooleanVar(value=entry["unlimitedExpiration"])
                var2._entry_ref = entry
                ctk.CTkCheckBox(self._table, text="", variable=var2,
                                width=20,
                                command=lambda v=var2:
                                    self._on_toggle(v, "unlimitedExpiration")
                                ).grid(row=i, column=4, padx=4, pady=2,
                                       sticky="w")
                rw["unlimitedExpiration"] = var2
            else:
                ctk.CTkLabel(self._table, text="—", text_color=TEXT_FAINT,
                             width=45).grid(
                    row=i, column=4, padx=4, pady=2, sticky="w")

            # col 5 — unlimitedLicenses checkbox
            if "unlimitedLicenses" in entry:
                var3 = ctk.BooleanVar(value=entry["unlimitedLicenses"])
                var3._entry_ref = entry
                ctk.CTkCheckBox(self._table, text="", variable=var3,
                                width=20,
                                command=lambda v=var3:
                                    self._on_toggle(v, "unlimitedLicenses")
                                ).grid(row=i, column=5, padx=4, pady=2,
                                       sticky="w")
                rw["unlimitedLicenses"] = var3
            else:
                ctk.CTkLabel(self._table, text="—", text_color=TEXT_FAINT,
                             width=45).grid(
                    row=i, column=5, padx=4, pady=2, sticky="w")

            self._row_widgets.append(rw)

        self._count_lbl.configure(
            text=f"{len(visible)} entries"
            + (f" (of {len(self._entries)})" if filt != "all" else ""))

    # ── Callbacks ──────────────────────────────────────────────────────

    def _on_toggle(self, var, field):
        var._entry_ref[field] = var.get()

    def _on_exp_change(self, widget):
        widget._entry_ref["expiration"] = widget.get().strip()

    def _bulk_bool(self, field, value: bool):
        n = 0
        for rw in self._row_widgets:
            var = rw.get(field)
            if var:
                var.set(value)
                rw["entry"][field] = value
                n += 1
        self._status.configure(
            text=f"{n} entries → {field}={value}",
            text_color=GREEN if value else WARN)

    # ── Save ───────────────────────────────────────────────────────────

    def _save(self):
        if not self._backup_data or not self._file_path:
            self._status.configure(text="No file loaded", text_color=ACCENT)
            return

        # flush any expiration entry still focused
        for rw in self._row_widgets:
            exp_w = rw.get("expiration")
            if exp_w:
                rw["entry"]["expiration"] = exp_w.get().strip()

        changes = 0
        for entry in self._entries:
            node = self._backup_data[entry["idx"]]
            obj = node.get(entry["type"], {})
            if not isinstance(obj, dict):
                continue
            for field in ("isDefault", "expiration",
                          "unlimitedExpiration", "unlimitedLicenses"):
                if field in entry and obj.get(field) != entry[field]:
                    obj[field] = entry[field]
                    changes += 1

        try:
            with open(self._file_path, "w") as f:
                json.dump(self._backup_data, f, indent=2, default=str)
            try:
                os.chmod(self._file_path, 0o600)
            except OSError:
                pass
            self._status.configure(
                text=f"Saved — {changes} change(s) → "
                     f"{os.path.basename(self._file_path)}",
                text_color=GREEN)
            cli_log(f"Edit Backup: saved {changes} change(s) → "
                    f"{os.path.basename(self._file_path)}", "success")
            if self._on_save:
                self._on_save(self._file_path)
        except Exception as e:
            self._status.configure(text=f"Save error: {e}", text_color=ACCENT)


# ═══════════════════════════════════════════════════════════════════════
#  Diff Panel — live side-by-side restore comparison
# ═══════════════════════════════════════════════════════════════════════

class DiffPanel(ctk.CTkFrame):
    """Side-by-side preview of what the loaded backup contains vs what
    the destination console currently has, for the currently-focused
    restore node.

    Left column  = backup file (parsed once when the file is loaded).
    Right column = destination snapshot — re-queried twice per node
                   during restore (before processing and after it
                   finishes) so the operator can watch the change land.
    """

    PHASE_LABELS = {
        "initial":  ("📷 initial",  "#888"),
        "before":   ("📷 pre-restore",  "#f0b248"),
        "after":    ("✅ post-restore", "#6dbf6d"),
    }

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        super().__init__(master, **kw)
        import tkinter as tk
        self._tk = tk
        self._backup: list = []
        # idx → {"phase": str, "at": str, "summary": list, "identity": dict}
        self._dest_snaps: dict = {}
        self._current_idx: Optional[int] = None

        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(8, 2))
        ctk.CTkLabel(hdr, text="🔍  Source vs Destination",
                     font=(UI_FONT, 13, "bold")).pack(side="left")
        self._refresh_lbl = ctk.CTkLabel(
            hdr, text="", font=(UI_FONT, 10), text_color=TEXT_MUTED)
        self._refresh_lbl.pack(side="right", padx=(4, 0))

        # ── Node selector ──
        self._node_var = ctk.StringVar(value="(no backup loaded)")
        self._node_menu = ctk.CTkOptionMenu(
            self, variable=self._node_var, values=["(no backup loaded)"],
            command=self._on_select_node, height=28,
            font=(MONO_FONT, 11))
        self._node_menu.pack(fill="x", padx=8, pady=(2, 4))

        # ── Column headers ──
        col_hdr = ctk.CTkFrame(self, fg_color="transparent")
        col_hdr.pack(fill="x", padx=8, pady=(0, 2))
        col_hdr.grid_columnconfigure(0, weight=1, uniform="c")
        col_hdr.grid_columnconfigure(1, weight=1, uniform="c")
        ctk.CTkLabel(col_hdr, text="📦  BACKUP",
                     font=(UI_FONT, 11, "bold"),
                     text_color=GREEN, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=4)
        ctk.CTkLabel(col_hdr, text="🌐  DESTINATION (live)",
                     font=(UI_FONT, 11, "bold"),
                     text_color=ACCENT, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=4)

        # ── Text widgets ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        body.grid_columnconfigure(0, weight=1, uniform="c")
        body.grid_columnconfigure(1, weight=1, uniform="c")
        body.grid_rowconfigure(0, weight=1)

        self._left = tk.Text(
            body, font=(MONO_FONT, 10), relief="flat", borderwidth=0,
            wrap="none", height=18)
        self._left.grid(row=0, column=0, sticky="nsew", padx=(4, 2))
        self._right = tk.Text(
            body, font=(MONO_FONT, 10), relief="flat", borderwidth=0,
            wrap="none", height=18)
        self._right.grid(row=0, column=1, sticky="nsew", padx=(2, 4))

        def _theme_diff(w):
            w.configure(bg=theme.tkcolor(("#FFFFFF", "#15171c")),
                        fg=theme.tkcolor(TEXT),
                        insertbackground=theme.tkcolor(TEXT))
            w.tag_configure("hdr",
                            foreground=theme.tkcolor(("#5A6270", "#9eaab8")),
                            font=(MONO_FONT, 10, "bold"))
            w.tag_configure("same",
                            foreground=theme.tkcolor(("#15803D", "#6dbf6d")))
            w.tag_configure("diff",
                            foreground=theme.tkcolor(("#B45309", "#f0b248")),
                            font=(MONO_FONT, 10, "bold"))
            w.tag_configure("missing",
                            foreground=theme.tkcolor(("#9AA0AC", "#666")),
                            font=(MONO_FONT, 10, "italic"))
            w.tag_configure("identity_diff",
                            foreground=theme.tkcolor(("#BE123C", "#e94560")),
                            font=(MONO_FONT, 10, "bold"))

        for w in (self._left, self._right):
            theme.tk_track(w, _theme_diff)
            w.configure(state="disabled")

        self._status = ctk.CTkLabel(
            self, text="Load a backup file and start a restore to see "
                       "side-by-side changes.",
            font=(UI_FONT, 10), text_color=TEXT_MUTED, anchor="w")
        self._status.pack(fill="x", padx=8, pady=(0, 6))

    # ── Public API ─────────────────────────────────────────────────────

    def set_backup(self, backup: list):
        """Called once when a backup file is loaded into RestorePage."""
        self._backup = backup or []
        self._dest_snaps.clear()
        labels = [self._label_for(i, n)
                  for i, n in enumerate(self._backup)]
        if not labels:
            labels = ["(empty backup)"]
            self._current_idx = None
        else:
            self._current_idx = 0
        self._node_menu.configure(values=labels)
        self._node_var.set(labels[0])
        self._render()

    def focus(self, idx: int):
        """Programmatic focus — used by the restore loop to follow the
        currently-processing node."""
        if not (0 <= idx < len(self._backup)):
            return
        self._current_idx = idx
        self._node_var.set(self._label_for(idx, self._backup[idx]))
        self._render()

    def record_dest_snapshot(self, idx: int, ntype: str, snap_data: dict,
                             phase: str):
        """Store the destination snapshot for node `idx`. Safe to call
        from a worker thread — UI redraw is marshalled to the main thread.
        """
        self._dest_snaps[idx] = {
            "ntype": ntype,
            "phase": phase,
            "at": datetime.now().strftime("%H:%M:%S"),
            "summary": _summarize_node_payload(snap_data),
            "identity": _dest_identity_from_data(ntype, snap_data),
        }
        # Marshal UI redraw if we're showing this node right now.
        if self._current_idx == idx:
            self.after(0, self._render)

    # ── Internals ──────────────────────────────────────────────────────

    @staticmethod
    def _label_for(i: int, node: dict) -> str:
        icon = {"global": "●", "account": "▸", "site": "  ▹",
                "group": "    ◦"}.get(node.get("type", ""), "")
        return f"{i+1:>3}. {icon} [{node.get('type','?'):<7}] {node.get('path','?')}"

    def _on_select_node(self, choice: str):
        for i, n in enumerate(self._backup):
            if self._label_for(i, n) == choice:
                self._current_idx = i
                break
        self._render()

    def _render(self):
        L, R = self._left, self._right
        L.configure(state="normal"); R.configure(state="normal")
        L.delete("1.0", "end"); R.delete("1.0", "end")

        if self._current_idx is None or not self._backup:
            L.insert("end", "(load a backup file)\n", "missing")
            R.insert("end", "(no node selected)\n", "missing")
            L.configure(state="disabled"); R.configure(state="disabled")
            return

        idx = self._current_idx
        node = self._backup[idx]
        ntype = node.get("type", "?")
        src_id = _node_identity(node)
        src_sum = _summarize_node_payload(node.get("data") or {})

        snap = self._dest_snaps.get(idx)
        dst_id = (snap or {}).get("identity") or {"type": ntype}
        dst_sum = (snap or {}).get("summary") or []

        # — Identity block —
        L.insert("end", f"━━━ Identity ━━━\n", "hdr")
        R.insert("end", f"━━━ Identity ━━━\n", "hdr")
        keys = ["path", "name", "group_type", "filterName", "filterId",
                "inherits", "state", "siteType"]
        for k in keys:
            sv = src_id.get(k)
            dv = dst_id.get(k)
            if sv is None and dv is None:
                continue
            sv_s = "" if sv is None else str(sv)
            dv_s = "" if dv is None else str(dv)
            same = (sv_s == dv_s)
            tag_l = "same" if same else "identity_diff"
            tag_r = "same" if same else "identity_diff"
            if not dv_s:
                tag_r = "missing"
            L.insert("end", f"  {k:<12}: {sv_s or '—'}\n", tag_l)
            R.insert("end", f"  {k:<12}: {dv_s or '—'}\n", tag_r)

        # — Elements block —
        L.insert("end", "\n━━━ Elements ━━━\n", "hdr")
        R.insert("end", "\n━━━ Elements ━━━\n", "hdr")
        # Build dest lookup by category for fast pairing.
        dst_by_cat = {cat: (cnt, names) for cat, cnt, names in dst_sum}
        for cat, scnt, snames in src_sum:
            dcnt, dnames = dst_by_cat.get(cat, (0, []))
            same = (scnt == dcnt)
            tag = "same" if same else "diff"
            L.insert("end",
                     f"  {cat:<16} = {scnt:>5}\n",
                     tag)
            R.insert("end",
                     f"  {cat:<16} = {dcnt:>5}"
                     f"{'   (Δ '+ ('+' if dcnt>scnt else '') + str(dcnt-scnt) +')' if not same else ''}\n",
                     tag)
            # Sample of names — first 5 per side, indented
            for name in snames[:5]:
                L.insert("end", f"      · {name}\n", "same")
            for name in dnames[:5]:
                in_src = name in snames
                t = "same" if in_src else "diff"
                R.insert("end", f"      · {name}\n", t)
            if len(snames) > 5:
                L.insert("end", f"      … {len(snames)-5} more\n", "missing")
            if len(dnames) > 5:
                R.insert("end", f"      … {len(dnames)-5} more\n", "missing")

        if snap:
            phase_label, color = self.PHASE_LABELS.get(
                snap["phase"], ("📷", "#888"))
            self._refresh_lbl.configure(
                text=f"{phase_label} @ {snap['at']}", text_color=color)
            self._status.configure(
                text=f"Destination snapshot taken at {snap['at']} "
                     f"({snap['phase']}).")
        else:
            self._refresh_lbl.configure(text="(not yet queried)",
                                         text_color=TEXT_FAINT)
            self._status.configure(
                text="Destination not queried yet — start a restore "
                     "to capture before/after snapshots.")

        L.configure(state="disabled"); R.configure(state="disabled")


# ═══════════════════════════════════════════════════════════════════════
#  Restore Page
# ═══════════════════════════════════════════════════════════════════════

class RestorePage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.backup_data = None
        self.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        ctk.CTkLabel(hdr, text="Restore to",
                     font=(UI_FONT, 22, "bold")).pack(side="left")
        self._console_var = ctk.StringVar(value="DESTINATION")
        ctk.CTkOptionMenu(hdr, values=["DESTINATION", "SOURCE"],
                          variable=self._console_var, width=160, height=32,
                          font=(UI_FONT, 14, "bold"),
                          command=lambda _: self._update_indicator()).pack(
            side="left", padx=(8, 0))
        self._indicator = ctk.CTkLabel(hdr, text="",
                                       font=(UI_FONT, 11),
                                       text_color=ACCENT)
        self._indicator.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(self,
                     text="Load a backup file and push configuration to the selected console.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # file picker
        file_row = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        file_row.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        file_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(file_row, text="Backup file:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=10, sticky="w")
        self.file_entry = ctk.CTkEntry(file_row, placeholder_text="Select a backup JSON…", height=32)
        self.file_entry.grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        ctk.CTkButton(file_row, text="Browse", width=80, height=32,
                      command=self._browse).grid(
            row=0, column=2, padx=12, pady=10)

        self.info_lbl = ctk.CTkLabel(file_row, text="",
                                     font=(UI_FONT, 12), text_color=TEXT_MUTED)
        self.info_lbl.grid(row=1, column=0, columnspan=3, padx=12,
                           pady=(0, 8), sticky="w")

        # ── Mangle Rename & Set Target Context (collapsible) ──
        mangle_outer = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        mangle_outer.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        self._mangle_collapsed = True

        mangle_hdr = ctk.CTkButton(
            mangle_outer,
            text="▶ Structure Operations (optional)",
            font=(UI_FONT, 13), fg_color="transparent",
            hover_color=NEUTRAL_HOVER, text_color=WARN, anchor="w", height=32,
            command=self._toggle_mangle)
        mangle_hdr.pack(fill="x", padx=8, pady=4)
        self._mangle_toggle_btn = mangle_hdr

        self._mangle_content = ctk.CTkFrame(mangle_outer, fg_color="transparent")
        # starts collapsed — don't pack
        self._mangle_content.columnconfigure(1, weight=1)

        ctk.CTkLabel(self._mangle_content, text="Source Name:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=4, sticky="w")
        self.mangle_src = ctk.CTkEntry(
            self._mangle_content,
            placeholder_text="e.g. Old Account/Old Site", height=32)
        self.mangle_src.grid(row=0, column=1, padx=12, pady=4, sticky="ew")

        ctk.CTkLabel(self._mangle_content, text="New Name:",
                     font=(UI_FONT, 13)).grid(
            row=1, column=0, padx=12, pady=4, sticky="w")
        self.mangle_dst = ctk.CTkEntry(
            self._mangle_content,
            placeholder_text="e.g. New Account/New Site", height=32)
        self.mangle_dst.grid(row=1, column=1, padx=12, pady=4, sticky="ew")

        mangle_btns = ctk.CTkFrame(self._mangle_content, fg_color="transparent")
        mangle_btns.grid(row=2, column=0, columnspan=2, padx=12,
                         pady=(6, 10), sticky="w")
        ctk.CTkButton(mangle_btns, text="Mangle Rename", height=34,
                      fg_color=BRAND,
                      command=self._mangle_rename).pack(side="left", padx=(0, 8))
        ctk.CTkButton(mangle_btns, text="Set Target Context", height=34,
                      fg_color=NEUTRAL,
                      command=self._set_target_context).pack(side="left", padx=(0, 8))
        self.mangle_status = ctk.CTkLabel(mangle_btns, text="",
                                          font=(UI_FONT, 11),
                                          text_color=TEXT_MUTED)
        self.mangle_status.pack(side="left", padx=8)

        # restore scope card
        scope_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        scope_card.grid(row=4, column=0, sticky="ew", padx=20, pady=4)
        scope_card.grid_columnconfigure(1, weight=1)
        scope_card.grid_columnconfigure(3, weight=1)
        scope_card.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(scope_card, text="Restore level:",
                     font=(UI_FONT, 13, "bold"), text_color=ACCENT).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        lv_inner = ctk.CTkFrame(scope_card, fg_color="transparent")
        lv_inner.grid(row=0, column=1, columnspan=5, padx=12, pady=8, sticky="w")
        self.restore_level_vars = {}
        for lv in ["global", "accounts", "sites", "groups"]:
            var = ctk.BooleanVar(value=(lv != "global"))
            ctk.CTkCheckBox(lv_inner, text=lv.capitalize(), variable=var,
                            font=(UI_FONT, 12)).pack(side="left", padx=8)
            self.restore_level_vars[lv] = var
        self.restore_level_vars["global"].trace_add(
            "write", lambda *a: self._toggle_restore_global())

        self._restore_scope_widgets = []
        for col_i, (lbl_text, attr) in enumerate([
            ("Account:", "restore_acct"),
            ("Site:", "restore_site"),
            ("Group:", "restore_group"),
        ]):
            c0 = col_i * 2
            lbl = ctk.CTkLabel(scope_card, text=lbl_text,
                               font=(UI_FONT, 13))
            lbl.grid(row=1, column=c0, padx=12, pady=6, sticky="w")
            entry = ctk.CTkEntry(
                scope_card, placeholder_text="(blank = all)", height=32)
            entry.grid(row=1, column=c0 + 1, padx=(0, 12), pady=6, sticky="ew")
            setattr(self, attr, entry)
            self._restore_scope_widgets.extend([lbl, entry])

        # element checkboxes (collapsible)
        self._restore_el_frame = ctk.CTkFrame(self, fg_color=CARD,
                                               corner_radius=12)
        self._restore_el_frame.grid(row=5, column=0, sticky="ew",
                                     padx=20, pady=4)
        _, self.restore_vars = _build_elements_section(
            self._restore_el_frame, row=0, title="Restore Elements")

        # ─────────────────────────────────────────────────────────────
        #  Action area — laid out in the order you actually work in:
        #     1 · PREPARE  (verify + safety, before anything is written)
        #     2 · RUN      (launch + live controls)
        #     3 · REVIEW   (results + recovery, after the run)
        # ─────────────────────────────────────────────────────────────
        def _phase_label(parent, text):
            return ctk.CTkLabel(parent, text=text, font=(UI_FONT, 11, "bold"),
                                text_color=TEXT_FAINT, width=78, anchor="w")

        # ── Phase 1 · PREPARE ──────────────────────────────────────────
        prep_row = ctk.CTkFrame(self, fg_color="transparent")
        prep_row.grid(row=6, column=0, sticky="ew", padx=20, pady=(10, 2))
        _phase_label(prep_row, "1 · PREPARE").pack(side="left", padx=(0, 6))

        self._preflight_btn = ctk.CTkButton(
            prep_row, text="✈  Pre-flight", height=34, width=120,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._preflight)
        self._preflight_btn.pack(side="left", padx=(0, 4))
        _help_btn(prep_row,
                  "Readiness check before you restore — destination "
                  "reachable, token valid/not-expiring and scoped wide "
                  "enough, and whether the target scope already exists. "
                  "Read-only."
                  ).pack(side="left", padx=(0, 8))
        self._preview_btn = ctk.CTkButton(
            prep_row, text="🔍  Preview vs Dest", height=34, width=160,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._preview_changes)
        self._preview_btn.pack(side="left", padx=(0, 4))
        _help_btn(prep_row,
                  "Dry run — compares the loaded backup against the LIVE "
                  "destination without writing anything. Shows how many items "
                  "per element would be newly created vs already exist, and "
                  "fills the Source-vs-Destination panel so you can review "
                  "before restoring."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(prep_row, text="⚙  Set Defaults", height=34, width=140,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      font=(UI_FONT, 12),
                      command=self._open_set_defaults).pack(side="left", padx=(0, 12))
        self._snapshot_var = ctk.BooleanVar(
            value=bool(self.app.settings.get("restore_snapshot_default", True)))
        ctk.CTkCheckBox(
            prep_row, text="📸 Snapshot first", variable=self._snapshot_var,
            font=(UI_FONT, 12)).pack(side="left", padx=(0, 2))
        _help_btn(prep_row,
                  "Before restoring, back up the destination's current state "
                  "of the selected elements/scope to a snapshot file. If the "
                  "restore goes wrong, use Rollback to load that snapshot and "
                  "restore the destination back to how it was."
                  ).pack(side="left", padx=(0, 4))

        # ── Phase 2 · RUN ──────────────────────────────────────────────
        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.grid(row=7, column=0, sticky="ew", padx=20, pady=(6, 2))
        _phase_label(action_row, "2 · RUN").pack(side="left", padx=(0, 6))

        # Launch (green tones)
        self._start_btn = ctk.CTkButton(
            action_row, text="▶  Restore", height=38, width=130,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            font=(UI_FONT, 14, "bold"),
            command=lambda: self._start_restore(auto=False))
        self._start_btn.pack(side="left", padx=(0, 4))
        self._auto_btn = ctk.CTkButton(
            action_row, text="⚡ Auto Restore", height=38, width=150,
            fg_color=GREEN_HOVER, hover_color=GREEN_HOVER,
            font=(UI_FONT, 14, "bold"),
            command=lambda: self._start_restore(auto=True))
        self._auto_btn.pack(side="left", padx=(0, 4))
        self._resume_btn = ctk.CTkButton(
            action_row, text="↻  Resume", height=38, width=120,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 14, "bold"),
            command=self._resume_restore, state="disabled")
        self._resume_btn.pack(side="left", padx=(0, 12))

        # Runtime control (disabled until running)
        self._stop_btn = ctk.CTkButton(
            action_row, text="■  Stop", height=38, width=90,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=(UI_FONT, 13, "bold"),
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 4))
        self._skip_btn = ctk.CTkButton(
            action_row, text=_SKIP_DEFAULT, height=38, width=180,
            fg_color=WARN_HOVER, hover_color=WARN_HOVER,
            font=(UI_FONT, 13, "bold"),
            command=self._skip_current_element, state="disabled")
        self._skip_btn.pack(side="left", padx=(0, 12))

        # Progress strip lives in its own full-width row below (see
        # progress_row) so it never crams the RUN buttons or floats mid-row.

        progress_row = ctk.CTkFrame(self, fg_color="transparent")
        progress_row.grid(row=8, column=0, sticky="ew", padx=20, pady=(2, 6))
        progress_row.grid_columnconfigure(0, weight=1)   # bar stretches

        self.progress = ctk.CTkProgressBar(progress_row, height=12,
                                           corner_radius=6,
                                           progress_color=GREEN)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.progress.set(0)
        self._timer_lbl = ctk.CTkLabel(progress_row, text="",
                                       font=(MONO_FONT, 12),
                                       text_color=TEXT_MUTED)
        self._timer_lbl.grid(row=0, column=1, sticky="e", padx=(0, 10))
        self._status_lbl = ctk.CTkLabel(progress_row, text="",
                                        font=(UI_FONT, 12, "bold"),
                                        text_color=TEXT_MUTED)
        self._status_lbl.grid(row=0, column=2, sticky="e")

        # ── Phase 3 · REVIEW ───────────────────────────────────────────
        review_row = ctk.CTkFrame(self, fg_color="transparent")
        review_row.grid(row=9, column=0, sticky="ew", padx=20, pady=(6, 4))
        _phase_label(review_row, "3 · REVIEW").pack(side="left", padx=(0, 6))

        self._export_btn = ctk.CTkButton(
            review_row, text="📋  Export Log", height=34, width=130,
            fg_color=BRAND, hover_color=BRAND_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._export, state="disabled")
        self._export_btn.pack(side="left", padx=(0, 4))
        self._explain_btn = ctk.CTkButton(
            review_row, text="🛟  Explain Errors", height=34, width=150,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._show_errors_dialog, state="disabled")
        self._explain_btn.pack(side="left", padx=(0, 4))
        _help_btn(review_row,
                  "After a restore, click this to see plain-English "
                  "explanations of every failure — what it means, why it "
                  "happened, what to do, and how to copy the error to send "
                  "to support."
                  ).pack(side="left", padx=(0, 8))
        self._redact_btn = ctk.CTkButton(
            review_row, text="🛡  Redacted Copy", height=34, width=150,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._export_redacted, state="disabled")
        self._redact_btn.pack(side="left", padx=(0, 4))
        _help_btn(review_row,
                  "Save a sanitised copy of the loaded backup with all "
                  "secrets (SMTP/AD/SSO/syslog passwords, tokens, keys) "
                  "masked — safe to attach to a ticket or share. The original "
                  "backup is untouched."
                  ).pack(side="left", padx=(0, 12))
        self._rollback_btn = ctk.CTkButton(
            review_row, text="↩  Rollback", height=34, width=120,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            font=(UI_FONT, 12, "bold"),
            command=self._load_last_snapshot)
        self._rollback_btn.pack(side="left", padx=(0, 4))
        _help_btn(review_row,
                  "Undo the last restore: loads the pre-restore snapshot and "
                  "restores the destination back to how it was. Only works if "
                  "'Snapshot first' (Prepare) was enabled for that run."
                  ).pack(side="left", padx=(0, 4))

        # progress table + diff panel (resizable side by side).
        # Use a tk.PanedWindow so the user can drag the divider to give
        # either side more room. PanedWindow requires its children to be
        # DIRECT Tk-path children, but CTkScrollableFrame wraps itself in
        # an internal canvas (its real Tk path is `…!canvas.!progresstable`,
        # not `…!progresstable`). So we add plain tk.Frame holders and
        # nest the actual widgets inside them.
        self.grid_rowconfigure(10, weight=1)
        import tkinter as _tk
        split = _tk.PanedWindow(
            self, orient="horizontal",
            sashwidth=8, sashrelief="raised",
            bd=0, sashpad=0,
            opaqueresize=True)
        theme.tk_track(split, lambda w: w.configure(bg=theme.tkcolor(CARD)))
        split.grid(row=10, column=0, sticky="nsew", padx=20, pady=(4, 12))

        # CRITICAL: PanedWindow doesn't constrain its children's heights —
        # without pack_propagate(False) the inner CTkScrollableFrame would
        # expand to fit all its rows (defeating the whole point of being
        # scrollable). Fixed initial height + propagate-off keeps the
        # scrollable region clipped so the scrollbar actually engages.
        left_pane = _tk.Frame(split, bd=0, highlightthickness=0, height=400)
        right_pane = _tk.Frame(split, bd=0, highlightthickness=0, height=400)
        for _p in (left_pane, right_pane):
            theme.tk_track(_p, lambda w: w.configure(bg=theme.tkcolor(CARD)))
        left_pane.pack_propagate(False)
        right_pane.pack_propagate(False)
        split.add(left_pane, minsize=300, stretch="always", width=620)
        split.add(right_pane, minsize=320, stretch="always", width=520)

        self.ptable = ProgressTable(left_pane, height=300)
        self.ptable.pack(fill="both", expand=True)
        self.diff_panel = DiffPanel(right_pane)
        self.diff_panel.pack(fill="both", expand=True)
        self._split = split

        self.log = _ConsoleProxy(self.app)
        self._timer_running = False
        self._timer_start = 0.0
        self._operation_log = []
        self._cancelled = False
        self._skip_element = False
        self._acct_id = ""  # set by JiraPage._load_ticket for ID-based validation

    def _tick_timer(self):
        if not self._timer_running:
            return
        import time
        elapsed = time.time() - self._timer_start
        m, s = divmod(int(elapsed), 60)
        self._timer_lbl.configure(text=f"{m:02d}:{s:02d}")
        self.after(500, self._tick_timer)

    def _toggle_restore_global(self):
        """When Global is checked, hide scope filters and elements."""
        is_global = self.restore_level_vars["global"].get()
        for w in self._restore_scope_widgets:
            if is_global:
                w.grid_remove()
            else:
                w.grid()
        if is_global:
            self._restore_el_frame.grid_remove()
        else:
            self._restore_el_frame.grid()

    def _update_indicator(self):
        choice = self._console_var.get()
        if choice == "DESTINATION":
            ctx = self.app.cfg.get_by_role("destination")
            color = ACCENT
            self.app.set_active_console("destination")
        else:
            ctx = self.app.cfg.get_by_role("source")
            color = GREEN
            self.app.set_active_console("source")
        if ctx:
            self._indicator.configure(
                text=f"▶ {ctx.name}  ({ctx.display_url})", text_color=color)
        else:
            self._indicator.configure(
                text=f"▶ {choice} — not connected", text_color=TEXT_MUTED)

    def on_show(self):
        self._update_indicator()
        self._auto_load_latest()

    def _open_set_defaults(self):
        path = self.file_entry.get().strip() or getattr(self.app, "_last_backup_path", None)
        SetDefaultsDialog(self, path, on_save=lambda p: self._load_file(p))

    def _toggle_mangle(self):
        if self._mangle_collapsed:
            self._mangle_collapsed = False
            self._mangle_content.pack(fill="x", padx=4, pady=(0, 4))
            self._mangle_toggle_btn.configure(
                text="▼ Structure Operations (optional)")
        else:
            self._mangle_collapsed = True
            self._mangle_content.pack_forget()
            self._mangle_toggle_btn.configure(
                text="▶ Structure Operations (optional)")

    def _auto_load_latest(self):
        """Auto-load the most recent backup JSON. Checks:
        1. Last backup created in this session (from Backup page)
        2. Most recent s1-backup/s1*.json in common directories
        """
        import glob

        # 1) Check if backup page just created a file
        last_path = getattr(self.app, "_last_backup_path", None)
        if last_path and os.path.isfile(last_path):
            current = self.file_entry.get().strip()
            if current == last_path and self.backup_data:
                return
            self._load_file(last_path)
            cli_log(f"Loaded backup from current session: "
                    f"{os.path.basename(last_path)}", "info")
            return

        # 2) Don't re-search if we already have data loaded
        if self.backup_data:
            return

        # 3) Search common directories + subdirectories
        search_dirs = set()
        for d in [
            os.path.expanduser("~"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
            os.getcwd(),
            os.path.dirname(os.path.abspath(__file__)),
        ]:
            if os.path.isdir(d):
                search_dirs.add(d)
                # also add parent dir (e.g. if running from s1-gui/)
                parent = os.path.dirname(d)
                if os.path.isdir(parent):
                    search_dirs.add(parent)

        candidates = []
        for d in search_dirs:
            candidates.extend(glob.glob(os.path.join(d, "s1-backup-*.json")))
            candidates.extend(glob.glob(os.path.join(d, "*backup*.json")))
            candidates.extend(glob.glob(os.path.join(d, "s1*.json")))
            # also check one level of subdirs
            candidates.extend(glob.glob(os.path.join(d, "*", "s1-backup-*.json")))
            candidates.extend(glob.glob(os.path.join(d, "*", "*backup*.json")))

        unique = list(set(f for f in candidates
                          if os.path.isfile(f) and f.endswith(".json")))
        if not unique:
            return
        latest = max(unique, key=os.path.getmtime)
        self._load_file(latest)
        cli_log(f"Auto-loaded: {latest}", "info")

    def _load_file(self, fp):
        """Load a backup JSON file and update the UI."""
        self.file_entry.delete(0, "end")
        self.file_entry.insert(0, fp)
        try:
            with open(fp, "r") as f:
                self.backup_data = json.load(f)
            n = len(self.backup_data)
            types = {}
            for node in self.backup_data:
                t = node.get("type", "?")
                types[t] = types.get(t, 0) + 1
            summary = ", ".join(f"{v} {k}(s)" for k, v in types.items())
            # Populate the diff panel so the operator can browse the
            # backup contents *before* clicking restore.
            if hasattr(self, "diff_panel"):
                try:
                    self.diff_panel.set_backup(self.backup_data)
                except Exception:
                    pass
            note = ""
            try:
                from export_utils import count_backup_secrets
                nsec = count_backup_secrets(self.backup_data)
                if hasattr(self, "_redact_btn"):
                    self._redact_btn.configure(
                        state="normal" if nsec else "disabled")
                if nsec:
                    note = (f"   ⚠ contains {nsec} secret value(s) — use "
                            f"'Redacted Copy' before sharing")
            except Exception:
                pass
            # Integrity check — surface a corrupt/incomplete backup up front.
            try:
                from migtools import check_backup_integrity
                rep = check_backup_integrity(self.backup_data)
                for w in rep["warnings"]:
                    cli_log(f"backup integrity: {w}", "warning")
                for e in rep["errors"]:
                    cli_log(f"backup integrity ERROR: {e}", "error")
                if not rep["ok"]:
                    note += "   ❌ integrity errors — see log"
                elif rep["warnings"]:
                    note += f"   ⚠ {len(rep['warnings'])} integrity warning(s)"
            except Exception:
                pass
            self.info_lbl.configure(
                text=f"Loaded {n} nodes: {summary}  "
                     f"({os.path.basename(fp)}){note}")
        except Exception as e:
            self.info_lbl.configure(text=f"Error: {e}")
            self.backup_data = None

    def _export_redacted(self):
        """Save a sanitised copy of the loaded backup (secrets masked), safe
        to share. The in-memory/working backup is not modified."""
        if not self.backup_data:
            messagebox.showwarning("No backup", "Load a backup file first.")
            return
        from export_utils import redact_backup
        redacted, count = redact_backup(self.backup_data)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = filedialog.asksaveasfilename(
            title="Export Redacted Backup Copy",
            initialfile=f"backup-redacted-{ts}",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(redacted, f, indent=2, default=str)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception as e:
            cli_log(f"Redacted export error: {e}", "error")
            messagebox.showerror("Export Error", str(e))
            return
        cli_log(f"Redacted copy saved → {os.path.basename(path)} "
                f"({count} secret(s) masked)", "success")
        messagebox.showinfo(
            "Redacted Copy Saved",
            f"Saved a shareable copy with {count} secret value(s) masked:\n"
            f"{path}\n\nNote: this redacted file is for sharing only — it "
            f"cannot be used to restore those secrets.")

    # ── Snapshot / rollback ───────────────────────────────────────────────
    def _snapshots_dir(self):
        d = os.path.join(os.path.expanduser("~"), ".s1-command-center",
                         "snapshots")
        os.makedirs(d, exist_ok=True)
        try:
            os.chmod(d, 0o700)  # holds full config dumps — owner-only
        except OSError:
            pass
        return d

    def _take_dest_snapshot(self, api, levels, filters, elements):
        """Back up the destination's CURRENT state (same scope + elements the
        restore will touch) to a snapshot file, so a bad restore can be rolled
        back. Reuses the exact backup reader (BackupPage._read_node) so the
        snapshot is byte-compatible with the normal restore loader. Returns the
        saved path, or None if nothing was captured.

        Runs on the restore worker thread (before _run_restore)."""
        bp = self.app.pages.get("Backup Source")
        if bp is None:
            raise RuntimeError("Backup engine unavailable for snapshot")

        nodes = _enumerate_tree(api, filters or {}, levels or {})
        total = len(nodes)
        out_nodes = []
        for idx, n in enumerate(nodes, 1):
            # Honor the Skip button ("⏭ Skip snapshot") — stop capturing and
            # let the restore proceed. Whatever was captured so far is kept.
            if self._skip_element or self._cancelled:
                break
            ntype, sid = n["type"], n["id"]
            scope = (_scope(ntype, sid) if ntype != "global"
                     else {"tenant": "true"})
            # Per-node progress so the snapshot never looks frozen: a full
            # destination backup can take a while, and a single static
            # "Snapshotting…" label reads as a hang. Show which node of how
            # many we're on (and hint that Skip works).
            self.after(0, lambda i=idx, t=total, p=n["path"]:
                       self._status_lbl.configure(
                           text=f"📸 Snapshot {i}/{t}: {p} "
                                f"(Skip to stop)…",
                           text_color=INFO))
            try:
                data = bp._read_node(api, ntype, sid, scope, elements, self.log)
            except Exception as exc:
                cli_log(f"Snapshot: could not read {n['path']}: {exc}",
                        "warning")
                continue
            node = {"path": n["path"], "type": ntype, "data": data}
            # Identity object under the key restore's _resolve_dest_id reads,
            # so the snapshot resolves back onto the SAME destination scopes.
            if ntype == "account":
                node["account"] = {"name": n["account_name"], "id": sid}
            elif ntype == "site":
                node["site"] = {"name": n["site_name"], "id": sid}
                node["account"] = {"name": n["account_name"]}
            elif ntype == "group":
                node["group"] = {"name": n["name"], "id": sid}
                node["site"] = {"name": n["site_name"]}
                node["account"] = {"name": n["account_name"]}
            node["backupMetadata"] = {
                "backupVersion": "gui-snapshot-1",
                "url": getattr(api, "base_url", ""),
                "snapshot": True,
                "start": datetime.now(timezone.utc).isoformat(),
            }
            out_nodes.append(node)

        if not out_nodes:
            return None
        host = (getattr(api, "base_url", "dest") or "dest")
        host = host.replace("https://", "").replace("http://", "").split("/")[0]
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self._snapshots_dir(),
                            f"snapshot-{host}-{ts}.json")
        with open(path, "w") as f:
            json.dump(out_nodes, f, indent=2, default=str)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def _latest_snapshot(self):
        d = self._snapshots_dir()
        snaps = [os.path.join(d, f) for f in os.listdir(d)
                 if f.startswith("snapshot-") and f.endswith(".json")]
        if not snaps:
            return None
        return max(snaps, key=os.path.getmtime)

    def _load_last_snapshot(self):
        """Load the most recent pre-restore snapshot into the restore loader so
        the operator can review it and restore it to revert the destination."""
        snap = self._latest_snapshot()
        if not snap:
            messagebox.showinfo(
                "No Snapshot",
                "No pre-restore snapshot found. Snapshots are created "
                "automatically before a restore when 'Snapshot first' is "
                "ticked.")
            return
        if not messagebox.askyesno(
                "↩ Rollback",
                f"Load this snapshot of the destination's PREVIOUS state?\n\n"
                f"{os.path.basename(snap)}\n\n"
                "It will become the loaded backup. Review it, make sure the "
                "DESTINATION console is selected, then click Restore to revert "
                "the destination to its pre-restore state."):
            return
        self._load_file(snap)
        cli_log(f"Rollback snapshot loaded → {os.path.basename(snap)}. "
                "Select DESTINATION and click Restore to revert.", "success")

    # ── Pre-flight readiness check (read-only) ────────────────────────────
    def _preflight(self):
        api = self._get_restore_api()
        if not api:
            return
        if not self.backup_data:
            messagebox.showwarning("No backup", "Load a backup file first.")
            return
        if getattr(self, "_preflighting", False):
            return
        self._preflighting = True
        self._preflight_btn.configure(state="disabled")
        self._status_lbl.configure(text="Pre-flight…", text_color=INFO)
        src_api = self.app.source_api
        backup = self.backup_data

        def do():
            from migtools import evaluate_preflight, preflight_verdict
            facts = {}
            try:
                api.get_my_user(); facts["dst_reachable"] = True
            except Exception:
                facts["dst_reachable"] = False
            if src_api is not None:
                try:
                    src_api.get_my_user(); facts["src_reachable"] = True
                except Exception:
                    facts["src_reachable"] = False
            # Destination token expiry / scope (best-effort; field names vary).
            try:
                td = api.get_token_details(api.api_token)
                d = td.get("data", td) if isinstance(td, dict) else {}
                facts["token_expires"] = (
                    d.get("expiresAt") or d.get("expiration")
                    or d.get("expiresAtUtc"))
                scope = (d.get("scope") or d.get("scopeLevel")
                         or d.get("scopeLevels"))
                if isinstance(scope, list):
                    scope = scope[0] if scope else None
                facts["token_scope"] = str(scope).lower() if scope else None
                facts["now"] = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
            # Deepest target level present in the backup.
            order = ["global", "account", "site", "group"]
            types = [n.get("type") for n in backup if n.get("type") in order]
            if types:
                facts["target_type"] = max(types, key=lambda t: order.index(t))
            # Does the first concrete target scope already exist?
            concrete = next((n for n in backup
                             if n.get("type") != "global"), None)
            if concrete is not None:
                try:
                    _id, found = self._resolve_dest_id_readonly(api, concrete)
                    facts["dest_scope_exists"] = found
                except Exception:
                    pass
            checks = evaluate_preflight(facts)
            return checks, preflight_verdict(checks)

        def done(result):
            checks, verdict = result
            self._preflighting = False
            self._preflight_btn.configure(state="normal")
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌",
                    "info": "ℹ️"}.get(verdict, "")
            self._status_lbl.configure(
                text=f"Pre-flight: {verdict}",
                text_color={"pass": GREEN, "warn": WARN,
                            "fail": ACCENT}.get(verdict, TEXT_MUTED))
            sym = {"pass": "✓", "warn": "⚠", "fail": "✗", "info": "•"}
            lines = [f"{sym.get(c.status, '•')} {c.name}: {c.detail}"
                     for c in checks]
            self._operation_log.append("— Pre-flight —")
            self._operation_log.extend(lines)
            for c in checks:
                cli_log(f"pre-flight {c.status}: {c.name} — {c.detail}",
                        "error" if c.status == "fail"
                        else "warning" if c.status == "warn" else "info")
            messagebox.showinfo(
                f"{icon} Pre-flight: {verdict.upper()}",
                "\n".join(lines) + (
                    "\n\n❌ Resolve the failures before restoring."
                    if verdict == "fail" else ""))

        def fail(e):
            self._preflighting = False
            self._preflight_btn.configure(state="normal")
            self._status_lbl.configure(text=f"Pre-flight error: {str(e)[:40]}",
                                        text_color=ACCENT)
            cli_log(f"Pre-flight failed: {e}", "error")

        run_async(self, do, done, fail)

    # ── Dry-run preview (read-only) ───────────────────────────────────────
    def _resolve_dest_id_readonly(self, api, node):
        """Resolve a backup node to a destination scope id WITHOUT creating
        anything (unlike _resolve_dest_id). Returns (id_or_empty, found_bool).
        Global → ("", True). Missing scope → ("", False)."""
        ntype = node.get("type")
        if ntype == "global":
            return "", True
        a_name = (node.get("account") or {}).get("name")
        s_name = (node.get("site") or {}).get("name")
        g_name = (node.get("group") or {}).get("name")
        try:
            accts = api.get_accounts()
        except Exception:
            return "", False
        acct = next((a for a in accts if a.get("name") == a_name), None)
        if ntype == "account":
            return (str(acct["id"]), True) if acct else ("", False)
        if not acct:
            return "", False
        try:
            sites = api.get_sites(params={"accountIds": acct["id"]})
        except Exception:
            return "", False
        site = next((s for s in sites if s.get("name") == s_name), None)
        if ntype == "site":
            return (str(site["id"]), True) if site else ("", False)
        if not site:
            return "", False
        try:
            groups = api.get_groups(params={"siteIds": site["id"]})
        except Exception:
            return "", False
        grp = next((g for g in groups if g.get("name") == g_name), None)
        return (str(grp["id"]), True) if grp else ("", False)

    def _preview_changes(self):
        """Dry run: compare the loaded backup against the live destination and
        report per-element create/exists counts, writing nothing."""
        api = self._get_restore_api()
        if not api:
            return
        if not self.backup_data:
            messagebox.showwarning("No backup", "Load a backup file first.")
            return
        if getattr(self, "_previewing", False):
            return
        self._previewing = True
        self._preview_btn.configure(state="disabled")
        self._status_lbl.configure(text="Previewing…", text_color=INFO)
        bp = self.app.pages.get("Backup Source")
        reader = bp._read_node if bp is not None else None

        def ui(fn):
            self.after(0, fn)

        def do():
            total_create = total_exists = 0
            missing_scopes = 0
            per_element = {}  # cat -> [create, exists]
            for idx, node in enumerate(self.backup_data):
                ntype = node.get("type", "?")
                dest_id, found = self._resolve_dest_id_readonly(api, node)
                bk_sum = _summarize_node_payload(node.get("data") or {})
                if not found:
                    missing_scopes += 1
                    # Whole scope absent → every backed-up item is "new".
                    for cat, cnt, _names in bk_sum:
                        if cnt:
                            per_element.setdefault(cat, [0, 0])[0] += cnt
                            total_create += cnt
                    continue
                dest_data = _fetch_dest_snapshot(api, ntype, dest_id,
                                                 reader=reader)
                if hasattr(self, "diff_panel"):
                    ui(lambda ii=idx, t=ntype, d=dest_data:
                       self.diff_panel.record_dest_snapshot(
                           ii, t, d, "initial"))
                dest_map = {c: (n, names) for c, n, names in
                            _summarize_node_payload(dest_data)}
                for cat, cnt, names in bk_sum:
                    if not cnt:
                        continue
                    dest_cnt, dnames = dest_map.get(cat, (0, []))
                    if names:
                        # Collection: compare item names as a multiset.
                        bc, dc = Counter(names), Counter(dnames)
                        create = sum((bc - dc).values())
                    else:
                        # Presence/config category (no item names): missing on
                        # the destination → would be created.
                        create = max(cnt - dest_cnt, 0)
                    exists = max(cnt - create, 0)
                    slot = per_element.setdefault(cat, [0, 0])
                    slot[0] += create
                    slot[1] += exists
                    total_create += create
                    total_exists += exists
            return {"create": total_create, "exists": total_exists,
                    "missing": missing_scopes, "per_element": per_element,
                    "nodes": len(self.backup_data)}

        def done(res):
            self._previewing = False
            self._preview_btn.configure(state="normal")
            self._status_lbl.configure(
                text=f"Preview: {res['create']} new, {res['exists']} exist",
                text_color=GREEN)
            lines = [
                f"Dry run vs {api.base_url}",
                f"{res['nodes']} node(s) · {res['missing']} scope(s) missing "
                f"on destination (would be created).",
                "",
                f"Items that would be NEWLY created: {res['create']}",
                f"Items that already exist (skipped/overwritten): "
                f"{res['exists']}",
                "",
                "Per element (new / exists):",
            ]
            for cat in sorted(res["per_element"]):
                c, e = res["per_element"][cat]
                if c or e:
                    lines.append(f"  • {_cat_label(cat)}: {c} new / {e} exist")
            self._operation_log.append("— Dry-run preview —")
            self._operation_log.extend(lines)
            cli_log("Dry-run preview complete (nothing was written).",
                    "success")
            messagebox.showinfo("Preview — Dry Run (no changes made)",
                                "\n".join(lines))

        def fail(e):
            self._previewing = False
            self._preview_btn.configure(state="normal")
            self._status_lbl.configure(text=f"Preview error: {str(e)[:40]}",
                                        text_color=ACCENT)
            cli_log(f"Preview failed: {e}", "error")

        run_async(self, do, done, fail)

    def _mangle_rename(self):
        """Rename accounts/sites/groups in the loaded backup data.
        Matches the CLI tool's mangle rename logic exactly:
          "Old Account/Old Site" → "New Account/New Site"
          "Old Account" → "New Account"
          "Old Account/Old Site/Old Group" → "New Account/New Site/New Group"
        Source and target must have the same number of path components.
        """
        if not self.backup_data:
            cli_log("No backup loaded. Browse for a file first.", "error")
            return
        source = self.mangle_src.get().strip()
        target = self.mangle_dst.get().strip()
        if not source or not target:
            cli_log("Fill both Source Name and New Name fields.", "error")
            return

        src_parts = source.split("/")
        tgt_parts = target.split("/")

        if len(src_parts) != len(tgt_parts):
            cli_log(f"Source has {len(src_parts)} parts, target has "
                    f"{len(tgt_parts)} — must be the same depth.\n"
                    f"Examples:\n"
                    f"  Account only: 'OldAcct' → 'NewAcct'\n"
                    f"  Account+Site: 'OldAcct/OldSite' → 'NewAcct/NewSite'\n"
                    f"  Keep account: 'Acct/OldSite' → 'Acct/NewSite'",
                    "error")
            return

        if len(src_parts) == 0 or len(src_parts) > 3:
            cli_log("Path must have 1-3 components (account, site, group).",
                    "error")
            return

        src_acct = src_parts[0] if len(src_parts) >= 1 else ""
        src_site = src_parts[1] if len(src_parts) >= 2 else ""
        src_group = src_parts[2] if len(src_parts) >= 3 else ""
        to_acct = tgt_parts[0] if len(tgt_parts) >= 1 else ""
        to_site = tgt_parts[1] if len(tgt_parts) >= 2 else ""
        to_group = tgt_parts[2] if len(tgt_parts) >= 3 else ""

        count = 0
        for node in self.backup_data:
            ntype = node.get("type", "")
            orig_path = node.get("path", "")
            path_parts = orig_path.rstrip("/").split("/")
            in_acct = path_parts[0] if len(path_parts) >= 1 else ""
            in_site = path_parts[1] if len(path_parts) >= 2 else ""
            in_group = path_parts[2] if len(path_parts) >= 3 else ""
            out_acct, out_site, out_group = in_acct, in_site, in_group

            if ntype == "global":
                continue

            if ntype == "account":
                if in_acct == src_acct:
                    out_acct = to_acct
                    node.get("account", {})["name"] = out_acct
                    new_path = f"{out_acct}/"
                else:
                    continue

            elif ntype == "site":
                if in_acct == src_acct:
                    out_acct = to_acct
                    if src_site and in_site == src_site:
                        out_site = to_site
                        node.get("site", {})["name"] = out_site
                    new_path = f"{out_acct}/{out_site}"
                else:
                    continue

            elif ntype == "group":
                if in_acct == src_acct:
                    out_acct = to_acct
                    if src_site and in_site == src_site:
                        out_site = to_site
                        if src_group and in_group == src_group:
                            out_group = to_group
                            node.get("group", {})["name"] = out_group
                    new_path = f"{out_acct}/{out_site}/{out_group}"
                else:
                    continue
            else:
                continue

            if node.get("path") != new_path:
                cli_log(f"  {ntype}: {orig_path} → {new_path}", "info")
                node["path"] = new_path
                count += 1

        self.mangle_status.configure(
            text=f"Renamed {count} node(s)", text_color=GREEN)
        cli_log(f"Mangle rename: '{source}' → '{target}' — "
                f"{count} nodes updated", "success")

    def _set_target_context(self):
        """Set restoreToContext in all backup nodes to the selected console."""
        if not self.backup_data:
            cli_log("No backup loaded. Browse for a file first.", "error")
            return
        choice = self._console_var.get().lower()
        ctx = self.app.cfg.get_by_role(
            "destination" if choice == "destination" else "source")
        if not ctx:
            cli_log(f"No {choice.upper()} console connected.", "error")
            return

        count = 0
        for node in self.backup_data:
            meta = node.get("backupMetadata")
            if meta is None:
                node["backupMetadata"] = {}
                meta = node["backupMetadata"]
            meta["restoreToContext"] = ctx.name
            meta["restoreToUrl"] = ctx.url
            count += 1

        self.mangle_status.configure(
            text=f"Target set → {ctx.name} ({count} nodes)", text_color=GREEN)
        cli_log(f"Set target context: {ctx.name} ({ctx.display_url}) — "
                f"{count} nodes updated", "success")

    def _browse(self):
        fp = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")], title="Select backup file")
        if not fp:
            return
        self._load_file(fp)

    def _get_restore_api(self):
        """Return the API for the selected console, with a warning if non-default."""
        choice = self._console_var.get()
        if choice == "DESTINATION":
            api = self.app.dest_api
            if not api:
                cli_log("No DESTINATION console connected.", "error")
                return None
            return api
        else:
            api = self.app.source_api
            if not api:
                cli_log("No SOURCE console connected.", "error")
                return None
            if not messagebox.askyesno(
                    "Non-standard direction",
                    "You are about to RESTORE to the SOURCE console.\n"
                    "Normally restores go to DESTINATION.\n\n"
                    "Are you sure you want to continue?"):
                return None
            return api

    def _skip_current_element(self):
        self._skip_element = True
        self._skip_btn.configure(state="disabled")
        cli_log("Skip requested — jumping to next element…", "warning")

    def _set_skip_label(self, label: str):
        """Rename the Skip button so it names the element/phase currently
        running (e.g. '⏭ Skip policy'), giving the operator a clear picture
        of what a Skip click will jump past. Safe to call from the restore
        worker thread — the widget update is marshalled to the UI thread."""
        text = _skip_button_text(label)
        self.after(0, lambda: self._skip_btn.configure(text=text))

    def _stop(self):
        self._cancelled = True
        self._stop_btn.configure(state="disabled")
        self._skip_btn.configure(state="disabled")
        self._status_lbl.configure(text="Stopping…", text_color=WARN)
        cli_log("Restore stop requested — finishing current node…", "warning")

    def _set_ui_running(self, running: bool):
        # Lock the rest of the app while a restore runs — only Stop, Skip
        # Element (and the OUTPUT drawer) stay clickable. The buttons this page
        # owns are exempted here and managed explicitly just below.
        self.app.set_busy(running, allow=(
            self._start_btn, self._auto_btn, self._resume_btn,
            self._stop_btn, self._skip_btn, self._export_btn,
            self._explain_btn))
        if running:
            self._start_btn.configure(state="disabled")
            self._auto_btn.configure(state="disabled")
            self._resume_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._skip_btn.configure(state="normal", text=_SKIP_DEFAULT)
            self._export_btn.configure(state="disabled")
            self._explain_btn.configure(state="disabled")
            self._status_lbl.configure(text="Restore running…",
                                        text_color=INFO)
        else:
            self._start_btn.configure(state="normal")
            self._auto_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._skip_btn.configure(state="disabled", text=_SKIP_DEFAULT)
            self._export_btn.configure(state="normal")
            # enable Explain Errors only if the last run produced any
            has_failures = any(
                n.get("failed_items")
                for n in getattr(self, "_report_nodes", []))
            self._explain_btn.configure(
                state="normal" if has_failures else "disabled")
            # enable Resume if the run was incomplete (cancelled / had errors)
            cp = getattr(self, "_checkpoint", {})
            has_remaining = any(
                v in ("cancelled", "error")
                for v in cp.values())
            self._resume_btn.configure(
                state="normal" if has_remaining else "disabled",
                fg_color=WARN if has_remaining else "#555")

    def _open_structure_ops_for_rename(self, src_name, dst_name=""):
        """Expand Structure Operations and prefill the Mangle Rename fields so
        the operator can rename the backup's account to the destination's."""
        if getattr(self, "_mangle_collapsed", False):
            self._toggle_mangle()
        try:
            self.mangle_src.delete(0, "end")
            self.mangle_src.insert(0, src_name or "")
            if dst_name:
                self.mangle_dst.delete(0, "end")
                self.mangle_dst.insert(0, dst_name)
            self.mangle_status.configure(
                text="Rename the account to match the destination, then Restore.",
                text_color=WARN)
            (self.mangle_dst if dst_name else self.mangle_src).focus_set()
        except Exception:
            pass

    def _check_account_name_match(self, api):
        """Before restoring, warn if NONE of the backup's account names exist on
        the destination console — that usually means the operator forgot to
        Mangle Rename the source account to the destination account name, and a
        restore would create a brand-new account instead of landing on the
        intended one. Returns "abort" if the restore should stop, else "ok"."""
        # Distinct account names referenced by non-global nodes in the backup.
        backup_accts = []
        for n in self.backup_data:
            if n.get("type") == "global":
                continue
            nm = (n.get("account") or {}).get("name")
            if nm and nm not in backup_accts:
                backup_accts.append(nm)
        if not backup_accts:
            return "ok"
        try:
            dest = api.get_accounts()
        except Exception:
            return "ok"   # network hiccup — don't block the restore
        dest_names = [a.get("name") for a in dest if a.get("name")]
        if not dest_names:
            return "ok"   # nothing to rename into; the account will be created
        # If ANY backup account already exists on the destination, assume the
        # mapping is intentional and don't nag.
        if any(nm in dest_names for nm in backup_accts):
            return "ok"

        src = backup_accts[0]
        dst_preview = dest_names[0] if len(dest_names) == 1 else ""
        dest_list = ", ".join(f'"{d}"' for d in dest_names[:5])
        if len(dest_names) > 5:
            dest_list += ", …"
        msg = (
            f'The backup\'s account "{src}" doesn\'t exist on the '
            f"{self._console_var.get()} console.\n\n"
            f"Destination account(s): {dest_list}\n\n"
            "If you meant to restore INTO an existing account, you likely need "
            "to Mangle Rename it first (Structure Operations) so the names "
            f'match — otherwise a NEW account named "{src}" will be created.\n\n'
            "Open Structure Operations to rename now?\n\n"
            "  • Yes — open Structure Operations (Mangle Rename)\n"
            "  • No — continue and create it as-is\n"
            "  • Cancel — stop")
        ans = messagebox.askyesnocancel("Account name mismatch", msg)
        if ans is None:
            return "abort"                      # Cancel
        if ans:                                 # Yes → redirect to rename
            self._open_structure_ops_for_rename(src, dst_preview)
            cli_log(
                f'Restore paused — account "{src}" isn\'t on the destination. '
                "Mangle Rename it in Structure Operations, then Restore again.",
                "warning")
            return "abort"
        return "ok"                             # No → continue as-is

    def _start_restore(self, auto=False):
        api = self._get_restore_api()
        if not api:
            return
        if not self.backup_data:
            messagebox.showwarning("No backup", "Load a backup file first.")
            return

        # auto-set target context to match the selected console
        choice = self._console_var.get().lower()
        ctx = self.app.cfg.get_by_role(
            "destination" if choice == "destination" else "source")
        if ctx:
            for node in self.backup_data:
                meta = node.get("backupMetadata")
                if meta is None:
                    node["backupMetadata"] = {}
                    meta = node["backupMetadata"]
                meta["restoreToContext"] = choice
                meta["restoreToUrl"] = ctx.url
            cli_log(f"Auto-set target context → {ctx.name} ({choice})", "info")

        levels = {k: v.get() for k, v in self.restore_level_vars.items()}
        if not auto:
            # Guard: if none of the backup's account names exist on the
            # destination, the operator probably forgot to Mangle Rename the
            # account (Structure Operations). Offer to jump there.
            if self._check_account_name_match(api) == "abort":
                return
            if levels.get("global"):
                if not messagebox.askyesno(
                        "⚠️ Global Restore",
                        "Global is checked — this will restore the ENTIRE console's "
                        "global-level configuration.\n\n"
                        "Are you sure you want to include Global?"):
                    return

            target = self._console_var.get()
            if not messagebox.askyesno(
                    "⚠️ Confirm Restore",
                    f"This will OVERWRITE settings on the {target} console.\n\n"
                    "This is potentially destructive. Only do this on a target "
                    "you intend to configure.\n\nProceed?"):
                return
        else:
            target = self._console_var.get()
            cli_log(f"⚡ Auto Restore — no prompts, creating everything "
                    f"on {target}.", "cmd")

        elements = [k for k, v in self.restore_vars.items() if v.get()]
        # In auto mode, clear name filters so nothing is skipped
        if auto:
            scope_filters = {"account": "", "site": "", "group": ""}
        else:
            scope_filters = {
                "account": self.restore_acct.get().strip().lower(),
                "site": self.restore_site.get().strip().lower(),
                "group": self.restore_group.get().strip().lower(),
            }
        import time as _time
        self.ptable.clear()
        self._operation_log = []
        self._skip_make_default_ids: set = set()  # sites created as Scenario B (no default override)
        self._auto_create_accounts = auto  # auto mode creates all accounts without asking
        self._auto_mode = auto  # suppresses all interactive prompts
        # _resume_checkpoint is set by _resume_restore() before calling
        # _start_restore(). For fresh starts, clear it so nothing is skipped.
        _was_resuming = getattr(self, "_is_resuming", False)
        if not hasattr(self, "_resume_checkpoint") or not _was_resuming:
            self._resume_checkpoint = {}
        self._is_resuming = False
        # Maps a resolved site's backup path -> destination site id. Groups
        # use this to find their parent site by the SAME identity that was
        # actually resolved/created — instead of re-looking-up by source name,
        # which breaks when the site was mapped onto (or renamed from) the
        # destination's existing "Default site".
        self._resolved_site_ids: dict = {}
        # Maps a backup node path -> list of failed_item dicts raised during
        # destination resolution (e.g. a default-site rename that the API
        # rejected). Merged into the node's failed_items so they show up in
        # the "Explain Errors" issues report instead of only the verbose log.
        self._resolve_issues: dict = {}
        self._report_nodes = []   # structured per-node report data
        self._report_meta = {     # report metadata
            "source_url": "",
            "dest_url": api.base_url,
            "dest_console": target,
            "customer": (ctx.name if ctx else target),
            "total_nodes": len(self.backup_data),
            "elements": elements,
            "filters": scope_filters,
            "levels": levels,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
        # get source URL from backup metadata
        for n in self.backup_data:
            m = n.get("backupMetadata", {})
            if m.get("url"):
                self._report_meta["source_url"] = m["url"]
                break
        self._cancelled = False
        self._skip_element = False
        self.progress.set(0)
        self._timer_start = _time.time()
        self._timer_running = True
        self._tick_timer()
        self._set_ui_running(True)
        cli_log(f"Starting restore to {target} console ({len(self.backup_data)} nodes)…", "cmd")

        # Snapshot the destination's current state before overwriting it, so
        # a bad restore can be rolled back. Skipped on resume (the snapshot was
        # already taken on the original run) and when the operator unticks it.
        take_snapshot = (getattr(self, "_snapshot_var", None) is not None
                         and self._snapshot_var.get()
                         and not _was_resuming)

        def do():
            if take_snapshot:
                self._set_skip_label("snapshot")
                self.after(0, lambda: self._status_lbl.configure(
                    text="📸 Snapshot: backing up destination "
                         "(for rollback)…", text_color=INFO))
                try:
                    snap = self._take_dest_snapshot(
                        api, levels, scope_filters, elements)
                    if snap:
                        self._report_meta["snapshot_path"] = snap
                        self._operation_log.append(
                            f"📸 Destination snapshot saved → {snap}")
                        cli_log(f"Destination snapshot saved → "
                                f"{os.path.basename(snap)} "
                                f"(use Rollback to revert)", "success")
                    else:
                        self._operation_log.append(
                            "📸 Snapshot captured no nodes (nothing to roll "
                            "back to).")
                except Exception as exc:
                    # Best-effort insurance — don't abort the restore, but make
                    # the failure loud so the operator knows rollback is off.
                    self._operation_log.append(
                        f"⚠ Destination snapshot FAILED: {exc} — "
                        f"rollback will not be available.")
                    cli_log(f"Destination snapshot failed: {exc}", "error")
                # A Skip clicked during the (potentially long) snapshot phase
                # leaves _skip_element set and the button disabled. Clear both
                # so the restore itself stays fully skippable; the partial
                # snapshot that was captured is still saved.
                if self._skip_element:
                    self._skip_element = False
                    self._operation_log.append(
                        "    ⏭ snapshot: skipped remaining by user request "
                        "(partial snapshot saved)")
                self.after(0, lambda: self._skip_btn.configure(
                    state="normal", text=_SKIP_DEFAULT))
                # Snapshot phase is done — clear its status text so the
                # lingering "📸 Snapshot…" label doesn't make the actual
                # restore look like it's still snapshotting.
                self.after(0, lambda: self._status_lbl.configure(
                    text="Restoring…", text_color=INFO))
            return self._run_restore(api, self.backup_data, elements,
                                     levels, scope_filters)

        def done(count):
            import time as _t
            self._timer_running = False
            self._set_ui_running(False)
            elapsed = _t.time() - self._timer_start
            m, s = divmod(int(elapsed), 60)
            if self._cancelled:
                self._timer_lbl.configure(
                    text=f"⊘ {m:02d}:{s:02d}", text_color=WARN)
                self._status_lbl.configure(
                    text=f"Stopped — {count} nodes restored",
                    text_color=WARN)
            else:
                self._timer_lbl.configure(
                    text=f"✓ {m:02d}:{s:02d}", text_color=GREEN)
                self._status_lbl.configure(
                    text=f"Done — {count} nodes",
                    text_color=GREEN)
            self._report_meta["end_time"] = datetime.now(timezone.utc).isoformat()
            self._report_meta["elapsed"] = f"{m}m {s}s"
            self._report_meta["restored_count"] = count
            self._report_meta["cancelled"] = self._cancelled
            self._operation_log.append(
                f"Restore: {count} nodes in {m}m {s}s")
            self.progress.set(1)
            self.app.set_status("Restore complete")
            cli_log(f"Restore: {count} nodes in {m}m {s}s", "success")
            self.app.log_audit(
                "restore", console=target,
                url=self._report_meta.get("dest_url", ""), nodes=count,
                elements=len(elements),
                snapshot=os.path.basename(
                    self._report_meta.get("snapshot_path", "")) or None,
                cancelled=self._cancelled)
            if not self._cancelled:
                try:
                    self._show_completion_popup()
                except Exception as _e:
                    cli_log(f"Completion popup error: {_e}", "warning")

        def fail(e):
            self._timer_running = False
            self._set_ui_running(False)
            self._timer_lbl.configure(text="✗ failed", text_color=ACCENT)
            self._status_lbl.configure(text=f"Error: {str(e)[:40]}",
                                        text_color=ACCENT)
            cli_log(f"Restore failed: {e}", "error")

        run_async(self, do, done, fail)

    def _resume_restore(self):
        """Resume a previously stopped/failed restore from where it left off.
        Nodes marked 'done' in the checkpoint are skipped; everything else
        (cancelled, error, skipped) is retried."""
        cp = getattr(self, "_checkpoint", {})
        if not cp:
            messagebox.showinfo("Nothing to Resume",
                                "No previous restore run to resume from.")
            return
        done_count = sum(1 for v in cp.values() if v == "done")
        remaining = sum(1 for v in cp.values() if v in ("cancelled", "error"))
        if remaining == 0:
            messagebox.showinfo("Nothing to Resume",
                                "All nodes completed — nothing to resume.")
            return
        if not messagebox.askyesno(
                "↻ Resume Restore",
                f"Previous run: {done_count} done, {remaining} remaining "
                f"(cancelled/error).\n\n"
                f"Resume will skip already-completed nodes and retry "
                f"the rest.\n\nContinue?"):
            return
        # Store checkpoint as resume source and re-launch with auto mode
        self._resume_checkpoint = dict(cp)
        self._is_resuming = True
        self._start_restore(auto=True)

    def _show_completion_popup(self):
        """Show a celebratory 'Migration Completed' dialog summarising the
        run for the destination customer. Triggered automatically when a
        restore finishes (not cancelled)."""
        meta = getattr(self, "_report_meta", {}) or {}
        nodes = getattr(self, "_report_nodes", []) or []
        total_failed = sum(len(n.get("failed_items", [])) for n in nodes)
        error_nodes = sum(1 for n in nodes if n.get("status") == "error")
        restored = meta.get("restored_count", 0)
        total = meta.get("total_nodes", 0)
        customer = (meta.get("customer") or meta.get("dest_console")
                    or "the destination")
        elements = meta.get("elements", []) or []
        elapsed = meta.get("elapsed", "?")
        clean = total_failed == 0

        def _fmt_ts(iso: str) -> str:
            if not iso:
                return "?"
            try:
                return (datetime.fromisoformat(iso.replace("Z", "+00:00"))
                        .astimezone()
                        .strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                return iso

        win = ctk.CTkToplevel(self)
        win.title("Migration Complete")
        win.configure(fg_color=CARD_ELEVATED)
        win.resizable(False, False)
        w, h = 560, 600

        # ── Header banner ──
        accent = GREEN if clean else WARN
        banner = ctk.CTkFrame(win, fg_color=CARD, corner_radius=0)
        banner.pack(fill="x")
        ctk.CTkLabel(
            banner,
            text="✓  Migration Completed Successfully" if clean
            else "✓  Migration Completed — with warnings",
            font=(UI_FONT, 19, "bold"), text_color=accent).pack(
            anchor="w", padx=24, pady=(18, 0))
        ctk.CTkLabel(
            banner, text=f"for  {customer}",
            font=(UI_FONT, 15), text_color=TEXT).pack(
            anchor="w", padx=24, pady=(2, 18))

        rows = [
            ("Destination", meta.get("dest_console", "?")),
            ("Destination URL", meta.get("dest_url", "?")),
            ("Source", meta.get("source_url", "?") or "—"),
            ("Nodes restored", f"{restored} of {total}"),
            ("Elements migrated", f"{len(elements)} type(s)"),
            ("Duration", elapsed),
            ("Failures",
             "None 🎉" if clean
             else f"{total_failed} item(s) across {error_nodes} node(s)"),
            ("Started", _fmt_ts(meta.get("start_time", ""))),
            ("Finished", _fmt_ts(meta.get("end_time", ""))),
        ]

        # Plain-text version of the whole report for one-click copy.
        # First line = Jira mention placeholder for the migration team (edit
        # after pasting so Jira resolves the @-mentions), followed by the
        # standard completion sentence with the tool version + scope name.
        scope_name = customer
        report_text = "\n".join(
            ["cc: @migration-team",
             f"Migration was completed with S1 Command Center v{APP_VERSION} "
             f"for the {scope_name}",
             ""]
            + [f"Migration {'Completed Successfully' if clean else 'Completed — with warnings'}",
               f"for {customer}", ""]
            + [f"{k}: {v}" for k, v in rows]
            + (["", "Elements: " + ", ".join(elements)] if elements else []))

        # ── Buttons (packed at the bottom FIRST so they are always
        #    visible — the expanding card below takes the remaining space) ──
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=20, pady=(0, 16))

        copy_status = ctk.CTkLabel(btns, text="", font=(UI_FONT, 11),
                                   text_color=GREEN)
        copy_status.pack(side="left", padx=(2, 0))

        def _copy_report():
            try:
                win.clipboard_clear()
                win.clipboard_append(report_text)
                copy_status.configure(text="Copied ✓")
                win.after(2000, lambda: copy_status.configure(text=""))
            except Exception as _e:
                copy_status.configure(text=f"Copy failed: {_e}",
                                      text_color=ACCENT)

        ctk.CTkButton(
            btns, text="Close", width=90, height=38,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            command=win.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btns, text="📋  Copy All", width=130, height=38,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            command=_copy_report).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btns, text="📄  Export Log", width=130, height=38,
            fg_color=BRAND, hover_color=BRAND_HOVER,
            command=self._export).pack(side="right", padx=(8, 0))
        if total_failed:
            ctk.CTkButton(
                btns, text="🛟  Explain Errors", width=150, height=38,
                fg_color=WARN, hover_color=WARN_HOVER,
                command=self._show_errors_dialog).pack(
                side="right", padx=(8, 0))

        # ── Detail card (fills the space between banner and buttons) ──
        card = ctk.CTkFrame(win, fg_color=CARD, corner_radius=12)
        card.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        card.grid_columnconfigure(1, weight=1)

        for r, (k, v) in enumerate(rows):
            ctk.CTkLabel(card, text=k, font=(UI_FONT, 12, "bold"),
                         text_color=TEXT_MUTED, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(16, 10),
                pady=5)
            val_color = (WARN if k == "Failures" and not clean
                         else GREEN if k == "Failures" else "white")
            ctk.CTkLabel(card, text=str(v), font=(UI_FONT, 12),
                         text_color=val_color, anchor="w",
                         wraplength=320, justify="left").grid(
                row=r, column=1, sticky="w", pady=5)

        if elements:
            ctk.CTkLabel(
                card, text="• " + ", ".join(elements),
                font=(UI_FONT, 10), text_color=TEXT_FAINT,
                wraplength=500, justify="left").grid(
                row=len(rows), column=0, columnspan=2,
                sticky="w", padx=16, pady=(8, 12))

        # center over the main window
        win.update_idletasks()
        try:
            root = self.winfo_toplevel()
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            rw, rh = root.winfo_width(), root.winfo_height()
            x = rx + max(0, (rw - w) // 2)
            y = ry + max(0, (rh - h) // 2)
        except Exception:
            x = y = 100
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.transient(self.winfo_toplevel())
        win.after(120, win.lift)
        win.after(150, win.grab_set)

    def _run_restore(self, api, backup, elements,
                     levels=None, scope_filters=None):
        pt = self.ptable

        def ui(fn):
            self.after(0, fn)

        def log(msg):
            self.after(0, lambda: self.log.log(msg))

        if levels is None:
            levels = {"global": True, "accounts": True, "sites": True, "groups": True}
        if scope_filters is None:
            scope_filters = {}
        acct_f = scope_filters.get("account", "")
        site_f = scope_filters.get("site", "")
        group_f = scope_filters.get("group", "")

        total = len(backup)

        # ── Build a source-side saved-filter id→name map ──
        # Group payloads sometimes carry `filterId` but not `filterName`
        # (older S1 API versions, or backups produced before filterName
        # enrichment was added). Without a name we can't resolve the filter
        # on the destination and dynamic groups silently fall back to
        # static. Walk every node's saved-filters blob once and cache.
        # Also build the dest-side cache lazily (keyed by site id).
        src_filter_names: dict[str, str] = {}
        for _n in backup:
            _d = _n.get("data") or {}
            for _f in ((_d.get("deepVisibility") or {}).get("filters") or []):
                fid, fname = _f.get("id"), _f.get("name")
                if fid and fname:
                    src_filter_names[str(fid)] = fname
            for _f in (_d.get("saved_filters") or []):
                fid, fname = _f.get("id"), _f.get("name")
                if fid and fname:
                    src_filter_names[str(fid)] = fname
        self._src_filter_id_to_name = src_filter_names
        self._dest_filter_cache: dict[str, dict] = {}

        # ── add all nodes as pending rows ──
        for i, node in enumerate(backup):
            ntype = node.get("type", "?")
            npath = node.get("path", "?")
            nid = f"r-{i}"
            ui(lambda n=nid, p=npath, t=ntype: pt.add_node(n, p, t))

        import time as _time
        _time.sleep(0.1)  # let UI render

        # Checkpoint: maps node index → status. Populated during the run
        # and reused by Resume to skip already-completed nodes.
        checkpoint = getattr(self, "_resume_checkpoint", {})
        self._checkpoint = {}  # fresh checkpoint for this run

        restored = 0
        skipped = 0
        for i, node in enumerate(backup):
            nid = f"r-{i}"
            ntype = node.get("type", "?")
            npath = node.get("path", "?")
            data = node.get("data", {})

            # cancellation
            if self._cancelled:
                for j in range(i, len(backup)):
                    ui(lambda n=f"r-{j}": pt.set_skipped(n, "cancelled"))
                    self._checkpoint[j] = "cancelled"
                self._operation_log.append(
                    f"— Restore cancelled after {restored} nodes —")
                break

            # ── Resume: skip nodes already completed in a previous run ──
            prev = checkpoint.get(i)
            if prev == "done":
                ui(lambda n=nid: pt.set_skipped(n, "already done (resumed)"))
                skipped += 1
                self._checkpoint[i] = "done"
                continue

            ui(lambda v=(i+1)/total: self.progress.set(v * 0.95))

            # ── skip expired/deleted ──
            obj = node.get(ntype, {}) if ntype in ("account", "site") else {}
            state = obj.get("state", "active").lower()
            if state in ("expired", "deleted", "disabled"):
                ui(lambda n=nid, s=state: pt.set_skipped(n, s))
                skipped += 1
                self._checkpoint[i] = "skipped"
                continue

            # ── level + name filter ──
            level_map = {"global": "global", "account": "accounts",
                         "site": "sites", "group": "groups"}
            level_key = level_map.get(ntype, "")
            if level_key and not levels.get(level_key):
                ui(lambda n=nid: pt.set_skipped(n, "level unchecked"))
                skipped += 1
                self._checkpoint[i] = "skipped"
                continue
            # When restoring at global level or auto-creating accounts,
            # the user wants a full migration — bypass name filters so
            # everything is restored (filters are usually ticket-paste
            # leftovers that don't apply to a global restore).
            _bypass_filters = (levels.get("global")
                               or getattr(self, "_auto_create_accounts", False))
            if ntype == "account":
                # Prefer npath (already updated by mangle-rename) over the
                # nested name field which is NOT updated by mangle-rename.
                nm = npath.strip("/").split("/")[0]
                if acct_f and acct_f not in nm.lower() and not _bypass_filters:
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; self._checkpoint[i] = "skipped"; continue
            elif ntype == "site":
                nm = node.get("site", {}).get("name", "")
                if site_f and site_f not in nm.lower() and not _bypass_filters:
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; self._checkpoint[i] = "skipped"; continue
            elif ntype == "group":
                nm = node.get("group", {}).get("name", "")
                if group_f and group_f not in nm.lower() and not _bypass_filters:
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; self._checkpoint[i] = "skipped"; continue

            # ── resolve destination (auto-create if needed) ──
            ui(lambda n=nid: pt.set_running(n))
            # Keep the status label in sync with the real phase so it never
            # shows a stale "📸 Snapshot…" while the restore is running.
            ui(lambda p=npath, x=i, t=total: self._status_lbl.configure(
                text=f"Restoring {x+1}/{t}: {p}…", text_color=INFO))
            ui(lambda n=nid: pt.set_detail(n, "resolving…"))
            # Follow the active node in the diff panel so the operator
            # always sees source-vs-dest for whatever is currently being
            # processed.
            ui(lambda ii=i: getattr(self, "diff_panel", None)
               and self.diff_panel.focus(ii))
            dest_id = self._resolve_dest_id(
                api, node, log,
                progress=lambda msg, n=nid: ui(
                    lambda m=msg, nn=n: pt.set_detail(nn, m)))
            if dest_id is None and ntype != "global":
                # show the last logged error from _resolve_dest_id
                errs = [l for l in self._operation_log if "✗" in l or "not found" in l]
                reason = errs[-1].strip() if errs else "resolve failed"
                ui(lambda n=nid, r=reason: pt.set_error(n, r))
                skipped += 1
                self._checkpoint[i] = "error"
                continue

            # ── Diff-panel: snapshot destination BEFORE we write to it ──
            # Network calls — runs in this worker thread.
            try:
                snap_before = _fetch_dest_snapshot(api, ntype, dest_id or "")
                if hasattr(self, "diff_panel"):
                    ui(lambda ii=i, t=ntype, d=snap_before:
                       self.diff_panel.record_dest_snapshot(
                           ii, t, d, "before"))
            except Exception as _e:
                pass

            # ── override default site if needed ──
            if ntype == "site" and dest_id:
                site_obj = node.get("site", {})
                # Skip default promotion for sites the user chose to create fresh (Scenario B)
                if str(dest_id) in self._skip_make_default_ids:
                    log(f"  Site '{site_obj.get('name')}' restored as non-default "
                        f"(user kept existing default site unchanged)")
                    self._operation_log.append(
                        f"  ℹ '{site_obj.get('name')}' created as new non-default site "
                        f"(Scenario B — existing default site preserved)")
                elif site_obj.get("isDefault"):
                    ui(lambda n=nid: pt.set_detail(n, "checking default site…"))
                    path_parts = npath.strip("/").split("/")
                    acct_name = path_parts[0] if path_parts else ""
                    try:
                        accts = api.get_accounts()
                        # Use ticket account ID to pick the right account when names are duplicate
                        dest_acct_id = getattr(self, "_acct_id", "").strip()
                        if dest_acct_id:
                            acct_match = [a for a in accts
                                          if str(a.get("id", "")) == dest_acct_id]
                            if not acct_match:
                                acct_match = [a for a in accts
                                              if a.get("name") == acct_name]
                        else:
                            acct_match = [a for a in accts
                                          if a.get("name") == acct_name]
                        if acct_match:
                            acct_id = acct_match[0]["id"]
                            all_sites = api.get_sites(
                                params={"accountIds": acct_id})
                            existing_default = [
                                s for s in all_sites
                                if s.get("isDefault")
                                and str(s.get("id")) != str(dest_id)]
                            if existing_default:
                                cur = existing_default[0]
                                cur_name = cur.get("name", "?")
                                new_name = site_obj.get("name", "?")
                                import threading as _thr
                                answer = [None]
                                evt = _thr.Event()
                                def _ask():
                                    answer[0] = messagebox.askyesno(
                                        "Default Site Exists",
                                        f"Account '{acct_name}' already has a "
                                        f"default site:\n\n"
                                        f"  Current default:  {cur_name}\n"
                                        f"  New default:        {new_name}\n\n"
                                        f"Override '{cur_name}' and set "
                                        f"'{new_name}' as the default?")
                                    evt.set()
                                ui(lambda: _ask())
                                ui(lambda n=nid: pt.set_detail(
                                    n, f"⏸ waiting — default site "
                                       f"'{cur_name}' exists…"))
                                evt.wait()
                                if not answer[0]:
                                    log(f"  Skipped default override for "
                                        f"'{new_name}' (user declined)")
                                    self._operation_log.append(
                                        f"  ⊘ Skipped default override: "
                                        f"'{new_name}' (user declined)")
                                    ui(lambda n=nid: pt.set_detail(
                                        n, "default override skipped"))
                                else:
                                    ui(lambda n=nid: pt.set_detail(
                                        n, "overriding default site…"))
                                    for s in existing_default:
                                        api.update_site(s["id"],
                                                        {"isDefault": False})
                                        log(f"  Unset default on site "
                                            f"'{s.get('name')}'")
                                        self._operation_log.append(
                                            f"  ↻ Unset default: "
                                            f"'{s.get('name')}' "
                                            f"(id={s['id']})")
                                    api.update_site(dest_id,
                                                    {"isDefault": True, "name": new_name})
                                    log(f"  Set default + rename → '{new_name}'")
                                    self._operation_log.append(
                                        f"  ✓ Set default + renamed: "
                                        f"'{new_name}' (id={dest_id})")
                            else:
                                # no conflict — set default + rename
                                sname = site_obj.get("name", "")
                                update = {"isDefault": True}
                                if sname:
                                    update["name"] = sname
                                api.update_site(dest_id, update)
                                log(f"  Set default + rename → '{sname}'")
                                self._operation_log.append(
                                    f"  ✓ Set default + renamed: "
                                    f"'{sname}' (id={dest_id})")
                    except Exception as exc:
                        detail = str(getattr(exc, "detail", "") or exc)
                        log(f"  ⚠ Default override failed: {detail[:80]}")
                        self._operation_log.append(
                            f"  ⚠ Default override failed: {detail[:80]}")
                        self._resolve_issues.setdefault(npath, []).append({
                            "element": "site-rename",
                            "name": f"{site_obj.get('name', '?')} "
                                    f"(default site)",
                            "error": (f"default-site set/rename: "
                                      f"{detail[:300]}"),
                        })

            # Remember which destination site this backup path resolved to so
            # child groups can anchor to the SAME site even if it was mapped
            # onto (or renamed from) the destination's existing default site.
            if ntype == "site" and dest_id:
                self._resolved_site_ids[npath.strip("/")] = str(dest_id)

            scope = _scope(ntype, dest_id or "")
            restored += 1
            results = []
            failed_items = []  # collect per-item failures for report
            # Surface any failures raised during resolution (e.g. a default-
            # site rename the API rejected) in the issues report.
            failed_items.extend(self._resolve_issues.pop(npath, []))

            # _is_exists_error / _err_detail / _item_id are now module-level
            # helpers (defined near _scope) — hoisted out of this 3k-line
            # method so they can be unit-tested in isolation.

            def _r(label, fn, *a, **kw):
                """Restore helper: call fn, track ok/skip/fail."""
                self._set_skip_label(label)
                ui(lambda n=nid, l=label: pt.set_detail(n, f"restoring {l}…"))
                try:
                    fn(*a, **kw)
                    results.append((label, "ok"))
                except Exception as exc:
                    if _is_exists_error(exc):
                        results.append((label, "exists"))
                    else:
                        detail = _err_detail(exc)
                        results.append((label, f"ERR: {detail}"))
                        failed_items.append({
                            "element": label,
                            "name": label,
                            "error": str(detail)[:120],
                        })
                        self._operation_log.append(
                            f"    ✗ {label}: {exc}")
                # A single API call can't be interrupted mid-flight, so a Skip
                # clicked during this step lands too late to stop it. Absorb the
                # flag here (and re-enable the button) so it doesn't leak into —
                # and wrongly skip — the NEXT element. Cancel (Stop) is left set.
                if self._skip_element:
                    self._skip_element = False
                    ui(lambda: self._skip_btn.configure(state="normal"))
                    self._operation_log.append(
                        f"    ⏭ {label}: Skip clicked but step already "
                        f"completed (single-shot, not interruptible)")

            def _r_bulk(label, items, fn):
                """Bulk restore: create items one by one, skip existing."""
                item_list = items or []
                total_items = len(item_list)
                self._set_skip_label(label)
                ui(lambda n=nid, l=label, c=total_items:
                   pt.set_detail(n, f"restoring {l} (0/{c})…"))
                ok = skip = fail = 0
                last_err_msg = ""
                for idx, item in enumerate(item_list, 1):
                    if self._skip_element or self._cancelled:
                        skipped_remaining = total_items - idx + 1
                        skip += skipped_remaining
                        self._operation_log.append(
                            f"    ⏭ {label}: skipped {skipped_remaining} "
                            f"remaining item(s) by user request")
                        self._skip_element = False
                        ui(lambda: self._skip_btn.configure(state="normal"))
                        break
                    if idx % 5 == 1 or idx == total_items:
                        ui(lambda n=nid, l=label, x=idx, t=total_items:
                           pt.set_detail(n, f"restoring {l} ({x}/{t})…"))
                    try:
                        fn(item)
                        ok += 1
                    except Exception as exc:
                        if _is_exists_error(exc):
                            skip += 1
                        else:
                            fail += 1
                            # Persist the full error so the classifier sees
                            # the actual S1 reason; the console log gets the
                            # short version.
                            full_err = _err_detail(exc)
                            last_err_msg = full_err[:120]
                            failed_items.append({
                                "element": label,
                                "name": _item_id(item, label),
                                "error": full_err[:500],
                            })
                total = ok + skip + fail
                if total:
                    parts = []
                    if ok: parts.append(f"{ok} new")
                    if skip: parts.append(f"{skip} exist")
                    if fail: parts.append(f"{fail} err")
                    results.append((label, ", ".join(parts)))
                if last_err_msg:
                    self._operation_log.append(
                        f"    ✗ {label} last error: {last_err_msg}")
                    cli_log(f"{npath} {label}: {last_err_msg}", "error")

            def _skip_reset(label):
                """After a custom (non-_r_bulk) loop breaks on a Skip click,
                clear the flag and re-enable the button so the NEXT element is
                skippable again, and record it in the operation log. Cancel
                (Stop) is intentionally left set so the outer node loop halts
                too."""
                if self._skip_element:
                    self._skip_element = False
                    ui(lambda: self._skip_btn.configure(state="normal"))
                    self._operation_log.append(
                        f"    ⏭ {label}: skipped remaining by user request")

            def _summarize(result_key, ok, skip, fail, last_err):
                """Shared 'N new, N exist, N err' summary row + last-error log
                for the custom bulk blocks (exclusions / unified exclusions /
                firewall rules) that build their own payloads and so can't go
                through _r_bulk directly."""
                parts = []
                if ok: parts.append(f"{ok} new")
                if skip: parts.append(f"{skip} exist")
                if fail: parts.append(f"{fail} err")
                if parts:
                    results.append((result_key, ", ".join(parts)))
                if last_err:
                    self._operation_log.append(
                        f"    ✗ {result_key} last error: {last_err}")
                    cli_log(f"{npath} {result_key}: {last_err}", "error")

            def _set_cfg_decoupled(setter, cfg_data):
                """Apply a module (Firewall / Device Control / Network
                Quarantine) configuration, auto-decoupling the scope first if
                needed.

                When the destination scope still inherits from its parent, S1
                rejects the write with "...while inheriting settings from
                parent (code 4000010)". This helper is only reached when the
                SOURCE had a genuine override (the inherited-source case is
                skipped earlier), so we retry with inheritance explicitly
                broken to land the override. If decoupling can't be done, the
                ORIGINAL error is re-raised so the operator still gets the
                actionable 'decouple manually' guidance."""
                try:
                    return setter(scope, cfg_data)
                except Exception as exc:
                    msg = (str(exc) + " "
                           + str(getattr(exc, "detail", ""))).lower()
                    inheriting = any(w in msg for w in (
                        "inheriting settings from parent",
                        "while inheriting", "marking scope", "decoupled"))
                    if not inheriting:
                        raise
                    for breaker in ({"inheritedFrom": None},
                                    {"inherits": False},
                                    {"inheritedFrom": None,
                                     "inherits": False}):
                        try:
                            resp = setter(scope, {**cfg_data, **breaker})
                            self._operation_log.append(
                                f"    ↳ decoupled scope from parent and "
                                f"applied source override "
                                f"(via {'+'.join(breaker)})")
                            return resp
                        except Exception:
                            continue
                    raise exc  # decouple failed — surface the original reason

            # ── Policy ──
            if "policy" in elements and data.get("policy"):
                def _restore_policy(pol):
                    try:
                        return api.set_policy(ntype, dest_id or "", pol)
                    except Exception as exc:
                        msg = (str(exc) + " "
                               + str(getattr(exc, "detail", ""))).lower()
                        # The source policy's forensics auto-triggering
                        # references RemoteOps forensic-script profiles by
                        # ID; those profiles don't exist on the destination,
                        # so S1 rejects the policy with "Bad auto-triggering
                        # policy information provided (code 4000010)". Drop
                        # that block and retry so the rest of the policy
                        # still lands.
                        if "auto-triggering" in msg or "triggering" in msg:
                            self._operation_log.append(
                                "    ↳ dropped forensicsAutoTriggering "
                                "(source RemoteOps forensic profile not on "
                                "destination) and retried policy")
                            return api.set_policy(
                                ntype, dest_id or "",
                                _drop_forensics_triggering(pol))
                        raise
                _r("policy", _restore_policy, data["policy"])

            # ── Exclusions ──
            if "exclusions" in elements and data.get("exclusions"):
                self._set_skip_label("excl")
                e_ok = e_skip = e_fail = 0
                e_last_err = ""
                for etype, items in data["exclusions"].items():
                    if self._skip_element or self._cancelled:
                        break
                    for item in (items or []):
                        if self._skip_element or self._cancelled:
                            break
                        try:
                            payload = _whitelist(item, _EXCL_FIELDS)
                            # Scrub invisible bidi/zero-width chars that
                            # the destination validator rejects. Apply
                            # to free-text fields only — the type-enum
                            # fields are already controlled.
                            for f in ("value", "description"):
                                if isinstance(payload.get(f), str):
                                    payload[f] = _strip_non_printable(
                                        payload[f])
                            api.create_exclusion(scope, payload)
                            e_ok += 1
                        except Exception as exc:
                            if _is_exists_error(exc):
                                e_skip += 1
                            else:
                                e_fail += 1
                                # Keep full detail in the failure record so
                                # the error-classifier can match on it; the
                                # console line gets the short version.
                                full_err = _err_detail(exc)
                                e_last_err = full_err[:80]
                                failed_items.append({
                                    "element": f"excl/{etype}",
                                    "name": item.get("value", "?")[:80],
                                    "error": full_err[:500],
                                })
                _skip_reset("excl")
                _summarize("excl", e_ok, e_skip, e_fail, e_last_err)

            # ── Unified Exclusions ──
            if "unified_exclusions" in elements and data.get("unified_exclusions"):
                self._set_skip_label("unified-excl")
                u_ok = u_skip = u_fail = 0
                u_last_err = ""
                # Build the unified-exclusion filter with scopeLevel
                _ue_scope_map = {
                    "global": ("global", ""),
                    "account": ("account", dest_id or ""),
                    "site": ("site", dest_id or ""),
                    "group": ("group", dest_id or ""),
                }
                _ue_sl, _ue_slid = _ue_scope_map.get(ntype, ("site", dest_id or ""))
                ue_filter = dict(scope)
                ue_filter["scopeLevel"] = _ue_sl
                if _ue_slid:
                    ue_filter["scopeLevelId"] = _ue_slid
                for item in data["unified_exclusions"]:
                    if self._skip_element or self._cancelled:
                        break
                    try:
                        payload = _whitelist(item, _UNIFIED_EXCL_FIELDS)
                        # Map common field-name variants
                        if not payload.get("exclusionName"):
                            payload["exclusionName"] = (
                                item.get("name")
                                or item.get("exclusionName")
                                or item.get("value", "Migrated exclusion")
                            )
                        for f in ("value", "description", "exclusionName", "note"):
                            if isinstance(payload.get(f), str):
                                payload[f] = _strip_non_printable(payload[f])
                        # Truncate exclusion name to API limit (255 chars)
                        if isinstance(payload.get("exclusionName"), str) \
                                and len(payload["exclusionName"]) > _EXCL_NAME_MAX_LEN:
                            payload["exclusionName"] = \
                                payload["exclusionName"][:_EXCL_NAME_MAX_LEN]
                        # Supply required defaults the API mandates
                        if not payload.get("reason"):
                            payload["reason"] = item.get("reason") or "other"
                        if not payload.get("recommendation"):
                            payload["recommendation"] = item.get("recommendation") or "NONE"
                        if not payload.get("modeType") and item.get("modeType"):
                            payload["modeType"] = item["modeType"]
                        api.create_unified_exclusion(ue_filter, payload)
                        u_ok += 1
                    except Exception as exc:
                        if _is_exists_error(exc):
                            u_skip += 1
                        else:
                            u_fail += 1
                            full_err = _err_detail(exc)
                            u_last_err = full_err[:80]
                            failed_items.append({
                                "element": "unified_excl",
                                "name": (item.get("exclusionName")
                                         or item.get("name")
                                         or item.get("value", "?"))[:80],
                                "error": full_err[:500],
                            })
                _skip_reset("unified-excl")
                _summarize("unified-excl", u_ok, u_skip, u_fail, u_last_err)

            # ── Blocklist ──
            bl = data.get("restrictions") or data.get("blocklist") or []
            if "blocklist" in elements and bl:
                _r_bulk("blocklist", bl,
                        lambda item: api.create_restriction(scope, _whitelist(item, _BLOCKLIST_FIELDS)))

            # ── Firewall ──
            fw = data.get("firewall", {})
            if "firewall_config" in elements and (fw.get("config") or data.get("firewall_config")):
                fw_cfg = fw.get("config") or data.get("firewall_config")
                if ntype == "group" and _scope_inherits_config(node, fw_cfg):
                    self._operation_log.append(
                        "  ↻ fw-config skipped at group scope — source group "
                        "inherits from parent (destination already inherits)")
                    results.append(("fw-cfg", "inherited"))
                else:
                    _r("fw-cfg", _set_cfg_decoupled,
                       api.set_firewall_config, fw_cfg)
            fw_r = fw.get("rules") or data.get("firewall_rules") or []
            if "firewall_rules" in elements and fw_r:
                # Only restore rules that belong to THIS node's scope. The
                # API returns inherited rules at every level, so without
                # this filter account-scoped rules leak into site/group
                # restores (e.g. the Account level is unchecked, yet the
                # inherited account firewall rules still get re-created at
                # the site). Mirrors the Device Control scope filter below.
                _fw_inherited = len(fw_r)
                fw_r = _rules_for_scope(fw_r, ntype)
                if not fw_r:
                    log(f"  fw-rules: 0 rules at {ntype} scope "
                        f"({_fw_inherited} inherited rules skipped)")
            if "firewall_rules" in elements and fw_r:
                self._set_skip_label("fw-rules")
                sorted_fw = sorted(fw_r,
                    key=lambda r: r.get("order", 9999))
                new_fw_ids = []
                fw_ok = fw_skip = fw_fail = 0
                fw_last_err = ""
                fw_loc_stripped = 0
                for rule in sorted_fw:
                    if self._skip_element or self._cancelled:
                        break
                    cleaned = _whitelist(rule, _FW_RULE_FIELDS)
                    # avoid conflict: use os_types if present, drop osType
                    if "os_types" in cleaned and "osType" in cleaned:
                        del cleaned["osType"]
                    if "osTypes" in cleaned and "osType" in cleaned:
                        del cleaned["osType"]
                    # Multi-IP rules live in the plural host arrays; the
                    # singular localHost/remoteHost only holds the first
                    # host. When the plural form is present, drop the
                    # singular so it can't clobber the rule down to one IP.
                    if cleaned.get("remoteHosts") and "remoteHost" in cleaned:
                        del cleaned["remoteHost"]
                    if cleaned.get("localHosts") and "localHost" in cleaned:
                        del cleaned["localHost"]
                    try:
                        resp = api.create_firewall_rule(scope, cleaned)
                        new_id = (resp.get("data", {}).get("id")
                                  if isinstance(resp, dict) else None)
                        if new_id:
                            new_fw_ids.append(new_id)
                        fw_ok += 1
                    except Exception as exc:
                        if _is_exists_error(exc):
                            fw_skip += 1
                            continue
                        # Cross-console location IDs never match. When
                        # S1 says `Invalid locations for this scope`,
                        # drop the location binding and retry once so
                        # the rule lands as a location-agnostic rule.
                        err_low = _err_detail(exc).lower()
                        had_locations = any(
                            cleaned.get(k) for k in
                            ("locationIds", "location_ids",
                             "location", "locationType",
                             "location_type"))
                        if "invalid locations" in err_low and had_locations:
                            for k in ("locationIds", "location_ids",
                                      "location", "locationType",
                                      "location_type"):
                                cleaned.pop(k, None)
                            try:
                                resp = api.create_firewall_rule(
                                    scope, cleaned)
                                new_id = (resp.get("data", {}).get("id")
                                          if isinstance(resp, dict)
                                          else None)
                                if new_id:
                                    new_fw_ids.append(new_id)
                                fw_ok += 1
                                fw_loc_stripped += 1
                                continue
                            except Exception as exc2:
                                exc = exc2  # fall through to fail branch
                        fw_fail += 1
                        full_err = _err_detail(exc)
                        fw_last_err = full_err[:80]
                        failed_items.append({
                            "element": "fw-rule",
                            "name": rule.get("name", "?")[:80],
                            "error": full_err[:500],
                        })
                if fw_loc_stripped:
                    self._operation_log.append(
                        f"    ⚠ fw-rules: {fw_loc_stripped} rule(s) "
                        f"created without their original location "
                        f"binding (source location IDs don't exist on "
                        f"this destination — re-attach manually).")
                _skip_reset("fw-rules")
                _summarize("fw-rules", fw_ok, fw_skip, fw_fail, fw_last_err)
                if len(new_fw_ids) > 1:
                    try:
                        api.reorder_firewall_rules(scope, new_fw_ids)
                    except Exception:
                        pass

            # ── NQ ──
            nq = data.get("networkQuarantine", {})
            if "nq_config" in elements and nq.get("config"):
                if ntype == "group" and _scope_inherits_config(node, nq["config"]):
                    self._operation_log.append(
                        "  ↻ nq-config skipped at group scope — source group "
                        "inherits from parent (destination already inherits)")
                    results.append(("nq-cfg", "inherited"))
                else:
                    _r("nq-cfg", _set_cfg_decoupled,
                       api.set_nq_config, nq["config"])
            if "nq_rules" in elements and nq.get("rules"):
                _r_bulk("nq-rules", nq["rules"],
                        lambda rule: api.create_nq_rule(scope, _clean_for_restore(rule)))

            # ── Device Control ──
            dc = data.get("deviceControl", {})
            if "device_control_config" in elements and (dc.get("config") or data.get("device_control_config")):
                dc_cfg = dc.get("config") or data.get("device_control_config")
                if ntype == "group" and _scope_inherits_config(node, dc_cfg):
                    self._operation_log.append(
                        "  ↻ dc-config skipped at group scope — source group "
                        "inherits from parent (destination already inherits)")
                    results.append(("dc-cfg", "inherited"))
                else:
                    _r("dc-cfg", _set_cfg_decoupled,
                       api.set_device_control_config, dc_cfg)
            dc_r = dc.get("rules") or data.get("device_control_rules") or []
            if "device_control_rules" in elements and dc_r:
                # Only restore rules that actually belong to this node's scope.
                # The API returns inherited rules at every level, so without this
                # filter account-scoped rules appear inside site/group nodes and
                # would be incorrectly re-created (or silently fail) at the wrong scope.
                dc_r_scoped = _rules_for_scope(dc_r, ntype)
                if not dc_r_scoped:
                    log(f"  dc-rules: 0 rules at {ntype} scope "
                        f"({len(dc_r)} inherited rules skipped)")
                else:
                    self._set_skip_label("dc-rules")
                    sorted_dc = sorted(dc_r_scoped,
                                       key=lambda r: r.get("order", 9999))
                    new_dc_ids = []
                    dc_ok = dc_skip = dc_fail = 0
                    for rule in sorted_dc:
                        if self._skip_element or self._cancelled:
                            break
                        rname = rule.get("ruleName", "?")
                        try:
                            resp = api.create_device_control_rule(
                                scope, _whitelist(rule, _DC_RULE_FIELDS))
                            new_id = (resp.get("data", {}).get("id")
                                      if isinstance(resp, dict) else None)
                            if new_id:
                                new_dc_ids.append(new_id)
                            dc_ok += 1
                        except Exception as exc:
                            if _is_exists_error(exc):
                                dc_skip += 1
                            else:
                                dc_fail += 1
                                full_err = _err_detail(exc)
                                detail = full_err[:120]
                                log(f"  ✗ dc-rule '{rname}': {detail}")
                                self._operation_log.append(
                                    f"  ✗ DC rule '{rname}' failed: {detail}")
                                failed_items.append({
                                    "element": "dc-rule",
                                    "name": str(rname)[:80],
                                    "error": full_err[:500],
                                })
                    _skip_reset("dc-rules")
                    parts = []
                    if dc_ok:   parts.append(f"{dc_ok} new")
                    if dc_skip: parts.append(f"{dc_skip} exist")
                    if dc_fail: parts.append(f"{dc_fail} err")
                    results.append(("dc-rules", ", ".join(parts) or "0"))
                    if len(new_dc_ids) > 1:
                        try:
                            api.reorder_device_control_rules(scope, new_dc_ids)
                        except Exception:
                            pass

            # ── Tags ──
            cfg = data.get("config", {}) or {}
            tags = cfg.get("tags", {}) or {}

            def _create_tag(tag, tag_type):
                """POST /tags for one backed-up tag. `scope` is sent so the tag
                lands at this node's level (matching the reference CLI); if a
                console rejects it, retry without it — the {filter} envelope
                already targets the scope."""
                body = _tag_payload(tag, tag_type, ntype)
                try:
                    return api.create_tag(scope, body)
                except Exception as exc:
                    if _is_exists_error(exc) or "scope" not in body:
                        raise
                    if "scope" not in _err_detail(exc).lower():
                        raise
                    body.pop("scope", None)
                    return api.create_tag(scope, body)

            def _restore_tags(label, items, tag_type):
                """Restore one tag group. GET /tags returns inherited tags at
                every level, so keep only the ones this node owns. Always
                records a row — a silent no-op is how endpoint tags went
                missing without any error (Joshua Tooley, 2026-08)."""
                items = items or []
                own = _tags_for_scope(items, ntype)
                if not own:
                    if items:
                        log(f"  {label}: 0 tags at {ntype} scope "
                            f"({len(items)} inherited skipped)")
                    results.append((label, "0"))
                    return
                _r_bulk(label, own, lambda t: _create_tag(t, tag_type))

            if "tags_firewall" in elements:
                _restore_tags("tags-fw",
                              tags.get("firewall") or data.get("tags_firewall"),
                              "firewall")
            if "tags_network_quarantine" in elements:
                _restore_tags("tags-nq",
                              tags.get("networkQuarantine")
                              or data.get("tags_nq"),
                              "network-quarantine")
            if "tags_endpoint" in elements:
                # Device-inventory (Ranger) tags are named /tags objects…
                _restore_tags("tags-ep",
                              tags.get("deviceInventory")
                              or data.get("tags_endpoint"),
                              "device-inventory")
                # …while unified endpoint tags are key/value pairs created
                # through the Tag Manager API.
                ep_tags = cfg.get("endpointTags") or []
                if ep_tags:
                    _r_bulk("ep-tags", ep_tags,
                            lambda t: api.create_endpoint_tag(
                                _endpoint_tag_payload(t), scope))
                else:
                    results.append(("ep-tags", "0"))

            # ── STAR ──
            star = data.get("star") or data.get("star_rules") or []
            if "star_rules" in elements and star:
                # Only restore rules that belong to THIS node's own scope. The
                # /cloud-detection/rules API returns inherited rules at every
                # level, so without this an account rule gets re-created at
                # every child site (reported by DJ Wilhelm, 2026-07). Mirrors
                # the firewall/device-control scope filters above, and also
                # repairs OLD backups that captured the inherited rules.
                _star_inherited = len(star)
                star = _star_rules_for_scope(star, ntype)
                if not star:
                    log(f"  star: 0 rules at {ntype} scope "
                        f"({_star_inherited} inherited rules skipped)")
            if "star_rules" in elements and star:
                def _create_star(rule):
                    cleaned = _clean_for_restore(rule)
                    # Drop null-valued fields — the destination API rejects
                    # e.g. templateRuleId=null and treatAsThreat=null with
                    # "Field may not be null" (code 4000010). Nulls mean
                    # "use default", so dropping them is safe.
                    cleaned = {k: v for k, v in cleaned.items()
                               if v is not None}
                    # S1 requires a temporary STAR rule's expiration to be
                    # WITHIN THE NEXT SIX MONTHS. Source rules routinely carry
                    # a date that's already in the past (expired) or further
                    # out than six months — both rejected with "Expiration
                    # date must be within the next six months (code 4000010)".
                    # Clamp any out-of-range date to ~5 months ahead so it
                    # always satisfies the constraint with margin to spare.
                    if cleaned.get("expiration"):
                        try:
                            from datetime import timedelta
                            now = datetime.now(timezone.utc)
                            exp = datetime.fromisoformat(
                                cleaned["expiration"].replace("Z", "+00:00"))
                            six_months = now + timedelta(days=180)
                            if exp <= now or exp > six_months:
                                cleaned["expiration"] = (
                                    now + timedelta(days=150)).isoformat()
                        except Exception:
                            pass
                    api.create_star_rule(scope, cleaned)
                _r_bulk("star", star, _create_star)

            # ── Saved filters ──
            dv = data.get("deepVisibility", {})
            flt = (dv.get("filters") if dv else data.get("saved_filters")) or []
            if "saved_filters" in elements and flt:
                _r_bulk("dv-filters", flt,
                        lambda f: api.create_saved_filter(scope, _clean_for_restore(f)))

            # ── Config overrides ──
            ovr = data.get("config", {}).get("overrides") or []
            if "config_overrides" in elements and ovr:
                # NOTE: S1 requires `data.scope` (a string like "site" /
                # "account" / "group" / "global") even though the wrapping
                # `filter` already names the scope. `_clean_for_restore`
                # strips the source's `scope` field, so we re-inject it here
                # using the destination scope type. Without this the API
                # rejects every create with "data: scope: Missing data for
                # required field." See restore-error bundle (v1.2.0).
                def _build_override(o):
                    body = _clean_for_restore(o)
                    body["scope"] = ntype
                    return body

                def _create_override(o):
                    body = _build_override(o)
                    try:
                        return api.create_config_override(scope, body)
                    except Exception as exc:
                        msg = (str(exc) + " "
                               + str(getattr(exc, "detail", ""))).lower()
                        # The POST /config-override filter does not accept
                        # `accountIds` ("filter: accountIds: Unknown field").
                        # The scope binding already travels in `data.scope`,
                        # so retry once with the rejected key dropped from
                        # the filter.
                        if "accountids" in msg and "unknown field" in msg:
                            alt = {k: v for k, v in scope.items()
                                   if k != "accountIds"}
                            return api.create_config_override(alt, body)
                        # Single-account consoles reject scope="global" and
                        # filter.tenant.  Map the override to account scope
                        # and retry with the destination account ID.
                        if (("global" in msg
                             and "not a valid choice" in msg)
                                or ("tenant" in msg
                                    and "unknown field" in msg)):
                            body["scope"] = "account"
                            alt = {k: v for k, v in scope.items()
                                   if k != "tenant"}
                            acct_id = getattr(self, "_acct_id", "").strip()
                            if acct_id:
                                alt["accountIds"] = [acct_id]
                            self._operation_log.append(
                                f"    ↳ retrying override at account scope "
                                f"(destination has no global scope)")
                            try:
                                return api.create_config_override(alt, body)
                            except Exception as exc2:
                                m2 = (str(exc2) + " "
                                      + str(getattr(exc2, "detail",
                                                    ""))).lower()
                                if ("accountids" in m2
                                        and "unknown field" in m2):
                                    alt2 = {k: v for k, v in alt.items()
                                            if k != "accountIds"}
                                    return api.create_config_override(
                                        alt2, body)
                                raise
                        raise
                _r_bulk("overrides", ovr, _create_override)

            # ── Settings ──
            stg = data.get("settings", {})
            for skey, setter in [
                ("notifications", api.set_notification_settings),
                ("syslog", api.set_syslog_settings),
                ("activeDirectory", api.set_ad_settings),
            ]:
                if stg.get(skey):
                    _r(f"set-{skey[:4]}", setter, scope,
                       _clean_for_restore(stg[skey]))
            # SMTP: the API never returns passwords, so the PUT always
            # fails with "Password is missing". Show a gentle skip
            # instead of a scary error.
            if stg.get("smtp"):
                self._set_skip_label("set-smtp")
                ui(lambda n=nid: pt.set_detail(n, "restoring set-smtp…"))
                try:
                    api.set_smtp_settings(scope,
                                          _clean_for_restore(stg["smtp"]))
                    results.append(("set-smtp", "ok"))
                except Exception as exc:
                    detail = _err_detail(exc).lower()
                    if "password" in detail and "missing" in detail:
                        results.append(("set-smtp",
                                        "skipped (password is write-only"
                                        " — re-enter manually)"))
                        self._operation_log.append(
                            "    ℹ SMTP: password not migrated (API "
                            "never returns it). Re-enter in destination "
                            "console → Settings → SMTP.")
                    else:
                        results.append(("set-smtp",
                                        f"ERR: {_err_detail(exc)}"))
                        failed_items.append({
                            "element": "set-smtp",
                            "name": "set-smtp",
                            "error": _err_detail(exc)[:500],
                        })

            # ── SSO (handled separately) ──
            # SSO is tenant-specific and the most failure-prone setting: the
            # destination often returns a 5xx when fed the source tenant's
            # SP/console-bound values. Try the full payload first, then retry
            # without the source-bound SP fields so the portable IdP-side
            # config (certificate, login URL, issuer) still lands.
            if stg.get("sso"):
                def _set_sso(cfg):
                    cleaned = _clean_sso_for_restore(cfg)
                    try:
                        return api.set_sso_settings(scope, cleaned)
                    except Exception:
                        stripped = {k: v for k, v in cleaned.items()
                                    if k not in _SSO_SP_BOUND}
                        if stripped != cleaned:
                            dropped = sorted(set(cleaned) & _SSO_SP_BOUND)
                            self._operation_log.append(
                                "    ↳ retrying SSO without source-tenant-"
                                f"bound field(s): {', '.join(dropped)}")
                            return api.set_sso_settings(scope, stripped)
                        raise
                # SSO is tenant-specific and frequently un-migratable (the
                # destination returns a 5xx because the SAML cert/URLs are
                # bound to the source tenant). Per operator request: try it
                # (with the SP-field retry above), but if it still fails just
                # SKIP it — keep the destination's own SSO config and do NOT
                # pollute the run with an SSO failure. The destination's
                # existing SSO is left untouched.
                try:
                    _set_sso(stg["sso"])
                    results.append(("set-sso", "ok"))
                except Exception as exc:
                    detail = _err_detail(exc)
                    results.append(("set-sso", "skipped"))
                    self._operation_log.append(
                        f"  ⊘ SSO not migrated — destination rejected it "
                        f"({detail[:100]}). Keeping the destination's own "
                        f"SSO config; configure SSO manually if needed.")
                    cli_log(f"{npath} set-sso skipped (not migratable): "
                            f"{detail[:120]}", "warning")
            if stg.get("recipients"):
                _r("recipients", api.set_notification_recipients,
                   scope, stg["recipients"])

            # ── Threat Intel ──
            ti = data.get("threatIntel") or []
            if "threat_intel" in elements and ti:
                self._set_skip_label("threat-intel")
                ok = fail = 0
                batch = []
                for ioc in ti:
                    if self._skip_element or self._cancelled:
                        break
                    batch.append(ioc)
                    if len(batch) >= 100:
                        try: api.upsert_threat_intel(scope, batch); ok += len(batch)
                        except Exception: fail += len(batch)
                        batch = []
                # Flush the final partial batch only if we weren't asked to
                # skip/stop mid-stream (an interrupted run leaves it unsent).
                if batch and not (self._skip_element or self._cancelled):
                    try: api.upsert_threat_intel(scope, batch); ok += len(batch)
                    except Exception: fail += len(batch)
                _skip_reset("threat-intel")
                results.append(("threat-intel", f"{ok}/{ok+fail}"))

            # ── Log collection rules ──
            lcr = data.get("logCollectionRules") or []
            if "log_collection_rules" in elements and lcr:
                _r_bulk("log-rules", lcr,
                        lambda r: api.create_log_collection_rule(_clean_for_restore(r)))

            # ── Auto-upgrade policies ──
            aup = data.get("autoUpgradePolicies") or []
            if "auto_upgrade_policies" in elements and aup:
                _r_bulk("upgrade-pol", aup,
                        lambda p: api.create_auto_upgrade_policy(_clean_for_restore(p)))

            # ── Locations ──
            # S1 only accepts location filters with accountIds / siteIds —
            # passing groupIds returns "Unknown field". Also the per-site
            # "Fallback" location is auto-created by S1 and has no
            # identifiers, so re-posting it returns "At least one identifier
            # must be defined". Skip both.
            locs = data.get("locations") or []
            if "locations" in elements and locs and ntype != "group":
                def _has_identifier(loc: dict) -> bool:
                    # S1 location identifiers: IP / range, MAC, DNS suffix,
                    # gateway, AD site, registry. Tolerate any non-empty
                    # identifier list.
                    for k in ("identifiers", "ipAddresses", "macAddresses",
                              "dnsSuffixes", "gatewayIps", "gatewayMacs",
                              "adSiteNames", "registryKeys", "subnets"):
                        v = loc.get(k)
                        if isinstance(v, list) and v:
                            return True
                    return False

                real_locs = [l for l in locs if _has_identifier(l)]
                skipped = len(locs) - len(real_locs)
                if skipped:
                    self._operation_log.append(
                        f"  ↻ Skipped {skipped} auto-created location(s) "
                        f"with no identifiers (e.g. Fallback)")
                if real_locs:
                    _r_bulk("locations", real_locs,
                            lambda l: api.create_location(
                                scope, _clean_for_restore(l)))
            elif "locations" in elements and locs and ntype == "group":
                # Quiet skip — locations don't exist at group scope on S1.
                self._operation_log.append(
                    f"  ↻ Locations skipped at group scope "
                    f"(S1 locations are site/account-only)")

            # ── Webhooks ──
            hooks = data.get("webhooks") or []
            if "webhooks" in elements and hooks:
                _r_bulk("webhooks", hooks,
                        lambda w: api.create_webhook(scope, _clean_for_restore(w)))

            # ── Scheduled reports ──
            sched = data.get("scheduledReports") or []
            if "scheduled_reports" in elements and sched:
                _r_bulk("sched-rep", sched,
                        lambda r: api.create_scheduled_report(
                            scope, _clean_for_restore(r)))

            # ── Marketplace inventory (read-only, log only) ──
            mkt = data.get("marketplaceApps") or []
            if "marketplace_apps" in elements and mkt:
                names = ", ".join(
                    (a.get("name") or a.get("applicationName") or "?")
                    for a in mkt[:20])
                more = f" (+{len(mkt) - 20} more)" if len(mkt) > 20 else ""
                self._operation_log.append(
                    f"  ℹ Marketplace apps to re-install manually "
                    f"({len(mkt)}): {names}{more}")
                results.append(("mkt-apps", f"{len(mkt)} listed"))

            # ── Remote Scripts library (inventory, log only) ──
            # The script body lives in per-tenant cloud storage and is not in
            # the backup payload, so scripts can't be re-created via the API.
            # List them so the operator can re-upload manually on the dest.
            scripts = data.get("scripts") or []
            if "scripts" in elements and scripts:
                names = ", ".join(
                    (s.get("scriptName") or s.get("name") or "?")
                    for s in scripts[:20])
                more = f" (+{len(scripts) - 20} more)" if len(scripts) > 20 else ""
                self._operation_log.append(
                    f"  ℹ Remote scripts to re-upload manually "
                    f"({len(scripts)}): {names}{more}")
                results.append(("scripts", f"{len(scripts)} listed"))

            roles = data.get("roles") or []
            if "roles" in elements and roles and ntype == "account":
                r_acct = dest_id or ""
                try:
                    existing_roles = {
                        (r.get("name") or "").strip().lower()
                        for r in (api.get_roles(
                            params={"accountIds": r_acct}) or [])}
                except Exception:
                    existing_roles = set()
                creatable_roles = []
                skipped_predef = 0
                for r in roles:
                    if not isinstance(r, dict):
                        continue
                    # Predefined roles exist on every console; the list/detail
                    # endpoints flag them via `predefined` OR `predefinedRole`.
                    if r.get("predefined") is True or r.get("predefinedRole") is True:
                        skipped_predef += 1
                        continue
                    nm = (r.get("name") or "").strip().lower()
                    if not nm or nm in existing_roles:
                        continue
                    creatable_roles.append(r)
                if skipped_predef:
                    self._operation_log.append(
                        f"  ℹ Skipped {skipped_predef} predefined role(s) — "
                        f"they exist on every console")
                if creatable_roles:
                    # Fetch the destination's create-ready role template once so
                    # every new role starts from the dest schema + licensed
                    # permission set (see _build_role_payload). Best-effort:
                    # fall back to a name/description-only payload if it fails.
                    scope_filter = _role_scope_filter(r_acct)
                    try:
                        role_template = api.get_role_template(
                            params={"accountIds": r_acct})
                    except Exception as e:
                        role_template = None
                        self._operation_log.append(
                            f"  ⚠ Role template unavailable ({e}); creating "
                            f"roles with name/description only")
                    _r_bulk("roles", creatable_roles,
                            lambda r: api.create_role(
                                _build_role_payload(r, role_template),
                                scope_filter))

            # ── Console (human) users ──
            # Only locally-created users can be provisioned via API. SSO/SCIM
            # users auto-provision on first login, so re-creating them here is
            # wrong (and the destination rejects it). Creating a user makes S1
            # send an invitation email — the operator opted in by ticking the
            # 'console_users' element.
            cusers = data.get("consoleUsers") or []
            if "console_users" in elements and cusers and ntype == "account":
                acct_id = dest_id or ""
                # Existing destination users (by email) so we skip duplicates.
                try:
                    existing = api.get_users(
                        params={"accountIds": acct_id}, max_items=500)
                    existing_emails = {
                        (u.get("email") or "").strip().lower()
                        for u in existing}
                except Exception:
                    existing_emails = set()
                # Destination roles by name → id, for role remapping (role IDs
                # never match across consoles, but built-in names do).
                try:
                    dest_roles = {
                        (r.get("name") or "").strip().lower(): r.get("id")
                        for r in ((api.get_roles() or [])
                                  + (api.get_roles(
                                      params={"accountIds": acct_id}) or []))}
                except Exception:
                    dest_roles = {}

                migratable = []
                skipped_remote = 0
                for u in cusers:
                    src = str(u.get("source") or u.get("origin") or "").lower()
                    if src and src != "local":
                        skipped_remote += 1  # sso / scim — auto-provisioned
                        continue
                    email = (u.get("email") or "").strip()
                    if not email or email.lower() in existing_emails:
                        continue
                    migratable.append(u)

                if skipped_remote:
                    self._operation_log.append(
                        f"  ℹ Skipped {skipped_remote} SSO/SCIM user(s) — "
                        f"they auto-provision on first login once SSO works")
                if migratable:
                    self._operation_log.append(
                        f"  ✉ Creating {len(migratable)} console user(s) — "
                        f"SentinelOne emails each one an invitation to log in")

                    def _create_user(u):
                        payload = {
                            "email": (u.get("email") or "").strip(),
                            "fullName": (u.get("fullName")
                                         or u.get("email") or ""),
                            "accountId": acct_id,
                        }
                        role_name = u.get("role")
                        if isinstance(role_name, str) and role_name.strip():
                            rid = dest_roles.get(role_name.strip().lower())
                            payload["role"] = rid or role_name
                        return api.create_user(payload)

                    _r_bulk("users", migratable, _create_user)

            # ── Build summary and update table ──
            ok_parts = []
            skip_parts = []
            err_parts = []
            for name, val in results:
                if val == "ok":
                    ok_parts.append(name)
                elif val == "exists":
                    skip_parts.append(name)
                elif isinstance(val, str) and val.startswith("ERR:"):
                    err_parts.append(f"{name}[{val[5:].strip()[:50]}]")
                elif val == "ERR":
                    err_parts.append(name)
                elif isinstance(val, str):
                    if "new" in val or "exist" in val or "err" in val:
                        ok_parts.append(f"{name}({val})")
                    else:
                        ok_parts.append(f"{name}:{val}")
            summary = ", ".join(ok_parts) if ok_parts else ""
            if skip_parts:
                summary += f"  ≡ {','.join(skip_parts)}" if summary else f"all exist: {','.join(skip_parts)}"
            if err_parts:
                summary += f"  ✗ {','.join(err_parts)}"
            if not summary:
                summary = "no data"

            if err_parts and not ok_parts:
                ui(lambda n=nid, s=summary: pt.set_error(n, s))
                self._checkpoint[i] = "error"
            else:
                ui(lambda n=nid, s=summary: pt.set_done(n, s))
                self._checkpoint[i] = "done"

            # ── Diff-panel: snapshot destination AFTER the writes land ──
            # This is the "after" state the operator wants to compare to
            # the backup. Same network cost as the "before" snapshot.
            try:
                snap_after = _fetch_dest_snapshot(api, ntype, dest_id or "")
                if hasattr(self, "diff_panel"):
                    ui(lambda ii=i, t=ntype, d=snap_after:
                       self.diff_panel.record_dest_snapshot(
                           ii, t, d, "after"))
            except Exception:
                pass

            # detailed log + structured report
            self._operation_log.append(
                f"[{ntype.upper()}] {npath} — {summary}")
            node_report = {
                "path": npath, "type": ntype, "status": "done",
                "summary": summary, "elements": {},
                "failed_items": failed_items,
            }
            for rname, rval in results:
                self._operation_log.append(f"  {rname}: {rval}")
                node_report["elements"][rname] = rval
            if err_parts and not ok_parts:
                node_report["status"] = "error"
            self._report_nodes.append(node_report)

        # ── Reorder groups by rank per site ──
        # collect groups: {site_id: [(rank, dest_group_id), ...]}
        site_groups = {}
        for node in backup:
            if node.get("type") != "group":
                continue
            grp = node.get("group", {})
            rank = grp.get("rank")
            if rank is None:
                continue
            npath = node.get("path", "").rstrip("/")
            parts = npath.split("/")
            if len(parts) < 2:
                continue
            acct_name = parts[0]
            site_name = parts[1]
            # find dest site ID
            try:
                accts = api.get_accounts()
                acct_match = [a for a in accts if a.get("name") == acct_name]
                if not acct_match:
                    continue
                all_sites = api.get_sites(params={"accountIds": acct_match[0]["id"]})
                site_match = [s for s in all_sites if s.get("name") == site_name]
                if not site_match:
                    continue
                site_id = site_match[0]["id"]
                # find dest group ID
                all_groups = api.get_groups(params={"siteIds": site_id})
                grp_match = [g for g in all_groups
                             if g.get("name") == grp.get("name")]
                if grp_match:
                    site_groups.setdefault(site_id, []).append(
                        (rank, grp_match[0]["id"]))
            except Exception:
                pass
        # reorder each site's groups
        for site_id, ranked in site_groups.items():
            ranked.sort(key=lambda x: x[0])
            ids = [gid for _, gid in ranked]
            if len(ids) > 1:
                try:
                    api.reorder_groups(site_id, ids)
                    self._operation_log.append(
                        f"  ✓ Reordered {len(ids)} groups in site {site_id}")
                except Exception as e:
                    self._operation_log.append(
                        f"  ⚠ Group reorder failed: {e}")

        self._operation_log.append(
            f"Total: {restored} restored, {skipped} skipped (of {total})")
        return restored

    def _resolve_dest_id(self, api, node, log, progress=None):
        """Resolve destination ID, auto-creating sites/groups if missing."""
        ntype = node.get("type")
        npath = node.get("path", "")
        _p = progress or (lambda msg: None)

        if ntype == "global":
            return None

        if ntype == "account":
            name = node.get("account", {}).get("name", "")
            _p(f"resolving account '{name}'…")
            accts = api.get_accounts()
            dest_acct_id = getattr(self, "_acct_id", "").strip()
            if dest_acct_id:
                # Prefer exact ID match — guarantees the right account even if name differs
                id_match = [a for a in accts if str(a.get("id", "")) == dest_acct_id]
                if id_match:
                    found = id_match[0]
                    _p(f"found account by ID → '{found['name']}' (id={dest_acct_id})")
                    if found.get("name") != name:
                        self._operation_log.append(
                            f"  ℹ Account name differs: backup has '{name}', "
                            f"destination has '{found['name']}' — matched by ID")
                    return found["id"]
                # ID not found — fall back to name match with a warning
                self._operation_log.append(
                    f"  ⚠ Target account ID {dest_acct_id} not found in destination "
                    f"— falling back to name match for '{name}'")
            match = [a for a in accts if a.get("name") == name]
            if match:
                found = match[0]
                if dest_acct_id and str(found.get("id", "")) != dest_acct_id:
                    self._operation_log.append(
                        f"  ⚠ Name-matched account '{name}' has ID {found['id']}, "
                        f"expected {dest_acct_id} — verify this is the correct account!")
                _p(f"found account → id={found['id']}")
                return found["id"]

            # ── Account not found — offer to create it ──
            if not self._auto_create_accounts:
                import threading as _thr
                # "create" | "create_all" | "skip"
                answer = [None]
                evt = _thr.Event()
                def _ask_create_acct(n=name):
                    dlg = ctk.CTkToplevel(self)
                    dlg.title("Account Not Found")
                    dlg.geometry("420x200")
                    dlg.resizable(False, False)
                    dlg.transient(self.winfo_toplevel())
                    try:
                        dlg.grab_set()
                    except Exception:
                        pass
                    ctk.CTkLabel(
                        dlg, text=f"Account '{n}' does not exist\n"
                        f"on the destination.",
                        font=(UI_FONT, 14, "bold"),
                        justify="center").pack(pady=(18, 12))
                    bf = ctk.CTkFrame(dlg, fg_color="transparent")
                    bf.pack(pady=8)
                    def _pick(v):
                        answer[0] = v
                        dlg.destroy()
                        evt.set()
                    ctk.CTkButton(
                        bf, text="Create", width=110, height=36,
                        fg_color=GREEN, hover_color=GREEN_HOVER,
                        font=(UI_FONT, 13, "bold"),
                        command=lambda: _pick("create")).pack(
                            side="left", padx=6)
                    ctk.CTkButton(
                        bf, text="Create All", width=110, height=36,
                        fg_color=BRAND, hover_color=BRAND_HOVER,
                        font=(UI_FONT, 13, "bold"),
                        command=lambda: _pick("create_all")).pack(
                            side="left", padx=6)
                    ctk.CTkButton(
                        bf, text="Skip", width=110, height=36,
                        fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                        font=(UI_FONT, 13, "bold"),
                        command=lambda: _pick("skip")).pack(
                            side="left", padx=6)
                    dlg.protocol("WM_DELETE_WINDOW",
                                 lambda: _pick("skip"))
                _p(f"⏸ account '{name}' not found — waiting for user…")
                self.after(0, _ask_create_acct)
                evt.wait()
                if answer[0] == "create_all":
                    self._auto_create_accounts = True
                    self._operation_log.append(
                        "  ✓ Auto-create enabled for all remaining accounts")
                    cli_log("Auto-creating all missing accounts from now on.",
                            "info")
                elif answer[0] == "skip":
                    self._operation_log.append(
                        f"  ⊘ Skipped account '{name}' (user declined create)")
                    _p(f"account '{name}' skipped")
                    return None
            # Build create payload.
            # S1 requires `licenses` with at least one bundle entry.
            # Use the DESTINATION's existing SKU — the source's bundle
            # may not be available on this tenant.
            src_acct = node.get("account", {}) or {}
            create_data = {"name": name}
            for field in ("accountType",):
                v = src_acct.get(field)
                if v:
                    create_data[field] = v
            # Detect the primary bundle from an existing destination
            # account. Only take the first bundle (the core SKU) — add-on
            # bundles (Purple AI, Ranger, etc.) may not be assignable to
            # new accounts and cause "not available in your scope" errors.
            sku_label = "?"
            primary_bundle = None
            try:
                existing = api.get_accounts()
                if existing:
                    dest_lic = existing[0].get("licenses", {})
                    bundles = dest_lic.get("bundles", [])
                    if bundles:
                        primary_bundle = bundles[0]
                        sku_label = primary_bundle.get("name", "?")
            except Exception:
                pass

            # Build license payloads: try full bundle first, then
            # stripped-down fallbacks if the API rejects add-ons/surfaces.
            attempts = []
            if primary_bundle:
                attempts.append({"bundles": [primary_bundle]})
                # fallback: bundle name only, no surfaces
                attempts.append({"bundles": [{"name": primary_bundle.get("name")}]})
            attempts.append({"bundles": [{"name": "Complete"}]})

            _p(f"creating account '{name}' (bundle={sku_label})…")
            last_err = ""
            for lic_payload in attempts:
                create_data["licenses"] = lic_payload
                try:
                    resp = api.create_account(create_data)
                    d = resp.get("data", {})
                    new_id = (d.get("id")
                              or (d.get("account", {}).get("id")
                                  if isinstance(d, dict) else None))
                    if new_id:
                        self._operation_log.append(
                            f"  ✓ AUTO-CREATED account '{name}' → id={new_id} "
                            f"(bundle={sku_label})")
                        _p(f"created account '{name}' → id={new_id}")
                        return new_id
                except Exception as exc:
                    last_err = getattr(exc, "detail", str(exc))
                    self._operation_log.append(
                        f"    ↳ attempt with {lic_payload} failed: "
                        f"{str(last_err)[:80]}")
            self._operation_log.append(
                f"  ✗ Account '{name}' create failed: {last_err}")
            cli_log(f"Account '{name}' create error: {last_err}", "error")
            return None

        if ntype == "site":
            sname = node.get("site", {}).get("name", "")
            src_site_is_default = node.get("site", {}).get("isDefault", False)
            path_parts = npath.strip("/").split("/")
            acct_name = path_parts[0] if path_parts else ""
            _p(f"finding account '{acct_name}'…")
            accts = api.get_accounts()

            # ── Account identity: prefer ticket account ID to avoid duplicate-name ambiguity ──
            dest_acct_id = getattr(self, "_acct_id", "").strip()
            if dest_acct_id:
                acct_match = [a for a in accts
                              if str(a.get("id", "")) == dest_acct_id]
                if acct_match:
                    _p(f"account matched by ID → '{acct_match[0]['name']}' "
                       f"(id={dest_acct_id})")
                    if acct_match[0].get("name") != acct_name:
                        self._operation_log.append(
                            f"  ℹ Account name in backup ('{acct_name}') differs from "
                            f"destination ('{acct_match[0]['name']}') — matched by ID {dest_acct_id}")
                else:
                    self._operation_log.append(
                        f"  ⚠ Account ID {dest_acct_id} not found — falling back to name match")
                    acct_match = [a for a in accts if a.get("name") == acct_name]
            else:
                acct_match = [a for a in accts if a.get("name") == acct_name]

            if not acct_match:
                self._operation_log.append(
                    f"  Site '{sname}': parent account '{acct_name}' not found")
                return None
            acct_id = acct_match[0]["id"]
            _p(f"looking up site '{sname}'…")
            all_sites = api.get_sites(params={"accountIds": acct_id})
            # only consider active sites
            active_sites = [s for s in all_sites
                            if s.get("state", "active").lower()
                            not in ("expired", "deleted", "disabled")]
            match = [s for s in active_sites if s.get("name") == sname]
            if match:
                mid = match[0]["id"]
                # verify site is actually writable
                try:
                    api.update_site(mid, {})
                    _p(f"found site → id={mid}")
                    return mid
                except Exception as ve:
                    sc = getattr(ve, "status_code", 0)
                    if sc == 404:
                        _p(f"site '{sname}' (id={mid}) returns 404 "
                           f"— skipping it")
                        self._operation_log.append(
                            f"  ⚠ Site '{sname}' (id={mid}) exists "
                            f"but returns 404 — treating as not found")
                        active_sites = [s for s in active_sites
                                        if s.get("id") != mid]
                    else:
                        # other error (e.g. 400) means the site exists
                        _p(f"found site → id={mid}")
                        return mid

            # ── Site not found in destination ───────────────────────────────
            import threading as _thr

            if active_sites:
                # ── Check for "default site" named conflict (Scenario A / B) ──
                # Conflict: source site is the default AND destination has a
                # placeholder named "default site".
                default_named = [s for s in active_sites
                                 if s.get("name", "").lower() == "default site"]
                if src_site_is_default and default_named:
                    placeholder = default_named[0]
                    ph_name = placeholder.get("name", "default site")
                    site_list = ", ".join(s.get("name", "?") for s in all_sites[:6])
                    # Auto mode: always overwrite the default site
                    if getattr(self, "_auto_mode", False):
                        answer = [True]
                    else:
                        answer = [None]
                        evt = _thr.Event()
                        def _ask_default_conflict(pn=ph_name, sn=sname,
                                                  an=acct_match[0].get("name", acct_name),
                                                  sl=site_list):
                            answer[0] = messagebox.askyesno(
                                "Default Site Conflict",
                                f"Source site  '{sn}'  is marked isDefault.\n"
                                f"Destination account  '{an}'  has a placeholder "
                                f"site named  '{pn}'.\n\n"
                                f"Destination sites: {sl}\n\n"
                                f"YES — Overwrite '{pn}' with source settings "
                                f"and rename it to '{sn}'.\n\n"
                                f"NO — Restore '{sn}' as a brand-new separate "
                                f"site ('{pn}' is left unchanged).")
                            evt.set()
                        _p(f"⏸ default-site conflict with '{ph_name}' — waiting for user…")
                        self.after(0, _ask_default_conflict)
                        evt.wait()
                    if answer[0]:
                        # Scenario A: overwrite placeholder
                        _p(f"Scenario A — overwriting '{ph_name}' → "
                           f"id={placeholder['id']}")
                        self._operation_log.append(
                            f"  ↻ Scenario A: overwriting '{ph_name}' "
                            f"with source default site '{sname}'")
                        return placeholder["id"]
                    else:
                        # Scenario B: create brand-new site; suppress default promotion
                        _p(f"Scenario B — creating '{sname}' as new site…")
                        self._operation_log.append(
                            f"  ➕ Scenario B: creating '{sname}' as new "
                            f"non-default site ('{ph_name}' left unchanged)")
                        # fall through to creation below — do NOT return None

                else:
                    # Generic: offer to map to the existing default / only site
                    existing_default = [s for s in active_sites if s.get("isDefault")]
                    candidate = (existing_default[0] if existing_default
                                 else active_sites[0] if len(active_sites) == 1
                                 else None)
                    if candidate:
                        ed_name = candidate.get("name", "?")
                        # Auto mode: always create new site
                        if getattr(self, "_auto_mode", False):
                            answer = [False]
                            _p(f"auto: creating '{sname}' as new site…")
                            self._operation_log.append(
                                f"  ➕ Auto: creating '{sname}' as a new site "
                                f"('{ed_name}' left unchanged)")
                        else:
                            _p(f"no match — asking what to do with '{sname}'…")
                            answer = [None]
                            evt = _thr.Event()
                            site_list = ", ".join(
                                s.get("name", "?") for s in all_sites[:6])
                            def _ask_map(en=ed_name, sn=sname,
                                         an=acct_match[0].get("name", acct_name),
                                         sl=site_list):
                                answer[0] = messagebox.askyesnocancel(
                                    "Site Not Found",
                                    f"Site '{sn}' was not found in account '{an}'.\n\n"
                                    f"Existing sites: {sl}\n\n"
                                    f"YES    — Map to '{en}' (rename it to '{sn}' and "
                                    f"restore settings onto it).\n\n"
                                    f"NO     — Create '{sn}' as a brand-new site in "
                                    f"this account.\n\n"
                                    f"Cancel — Skip '{sn}' entirely.")
                                evt.set()
                            self.after(0, _ask_map)
                            evt.wait()
                        if answer[0] is True:
                            # YES: map onto the existing site AND rename it to
                            # the source site name. The post-resolve default
                            # block only renames when the SOURCE site is the
                            # default, so a non-default mapping must be renamed
                            # here — otherwise the destination keeps its old
                            # name (e.g. stays 'Default site') even though the
                            # dialog promised to rename it.
                            cand_id = candidate["id"]
                            cand_name = candidate.get("name", "")
                            _p(f"mapping to '{ed_name}' → id={cand_id}")
                            if sname and sname != cand_name:
                                try:
                                    api.update_site(cand_id, {"name": sname})
                                    self._operation_log.append(
                                        f"  ↻ Mapped + renamed '{cand_name}' "
                                        f"→ '{sname}' (id={cand_id})")
                                except Exception as exc:
                                    detail = getattr(exc, "detail", str(exc))
                                    self._operation_log.append(
                                        f"  ⚠ Mapped '{sname}' onto "
                                        f"'{cand_name}' (id={cand_id}) but "
                                        f"RENAME FAILED: {str(detail)[:120]}")
                                    cli_log(f"Site rename '{cand_name}' → "
                                            f"'{sname}' failed: {detail}",
                                            "error")
                                    self._resolve_issues.setdefault(
                                        npath, []).append({
                                            "element": "site-rename",
                                            "name": f"{cand_name} → {sname}",
                                            "error": (f"PUT /sites/{cand_id} "
                                                      f"name rename: "
                                                      f"{str(detail)[:300]}"),
                                        })
                            else:
                                self._operation_log.append(
                                    f"  ↻ Mapped '{sname}' → existing "
                                    f"'{ed_name}' (id={cand_id})")
                            return cand_id
                        elif answer[0] is False:
                            # NO: create a new site — fall through to creation below
                            _p(f"creating '{sname}' as new site…")
                            self._operation_log.append(
                                f"  ➕ Creating '{sname}' as a new site "
                                f"('{ed_name}' left unchanged)")
                            # fall through — do NOT return
                        else:
                            # Cancel: skip
                            self._operation_log.append(
                                f"  ⊘ Skipped site '{sname}' (user cancelled)")
                            return None

            _p(f"creating site '{sname}'…")
            create_data = {"name": sname}
            site_obj = node.get("site", {})
            is_scenario_b = src_site_is_default  # new site created instead of overwriting default
            if site_obj.get("siteType"):
                create_data["siteType"] = site_obj["siteType"]
            if site_obj.get("suite"):
                create_data["suite"] = site_obj["suite"]
            elif site_obj.get("sku"):
                create_data["suite"] = site_obj["sku"]

            for attempt in range(2):
                try:
                    resp = api.create_site(acct_id, create_data)
                    d = resp.get("data", {})
                    new_id = (d.get("id")
                              or (d.get("site", {}).get("id")
                                  if isinstance(d, dict) else None))
                    if new_id:
                        self._operation_log.append(
                            f"  ✓ AUTO-CREATED site '{sname}' → id={new_id}")
                        if is_scenario_b:
                            # Mark this site so the main loop does NOT promote it to default
                            self._skip_make_default_ids.add(str(new_id))
                        return new_id
                    break
                except Exception as e:
                    detail = getattr(e, "detail", str(e))
                    # detect SKU/bundle mismatch
                    if attempt == 0 and "not available" in detail.lower() and "bundle" in detail.lower():
                        dest_sku = self._detect_dest_sku(api, acct_id)
                        if dest_sku and (getattr(self, "_auto_mode", False)
                                        or self._ask_sku_fix(detail, dest_sku)):
                            self._fix_sku_in_backup(dest_sku)
                            create_data["suite"] = dest_sku
                            continue  # retry with fixed SKU
                    self._operation_log.append(
                        f"  ✗ Site '{sname}' create failed: {detail}")
                    cli_log(f"Site '{sname}' create error: {detail}", "error")
                    break
            return None

        if ntype == "group":
            gname = node.get("group", {}).get("name", "")
            path_parts = npath.strip("/").split("/")
            acct_name = path_parts[0] if len(path_parts) > 0 else ""
            site_name = path_parts[1] if len(path_parts) > 1 else ""
            _p(f"finding account '{acct_name}'…")
            accts = api.get_accounts()
            acct_match = [a for a in accts if a.get("name") == acct_name]
            if not acct_match:
                self._operation_log.append(
                    f"  Group '{gname}': parent account '{acct_name}' not found")
                return None
            acct_id = acct_match[0]["id"]
            _p(f"finding site '{site_name}'…")
            all_sites = api.get_sites(params={"accountIds": acct_id})
            # Prefer the destination site this group's parent path already
            # resolved to during the site phase. This correctly follows a
            # site that was mapped onto (or renamed from) the destination's
            # existing "Default site", where a name lookup would fail.
            parent_site_path = "/".join(path_parts[:2])
            cached_site_id = self._resolved_site_ids.get(parent_site_path)
            site_id = None
            if cached_site_id and any(
                    str(s.get("id")) == str(cached_site_id) for s in all_sites):
                site_id = cached_site_id
                _p(f"using parent site resolved earlier → id={site_id}")
                self._operation_log.append(
                    f"  ↳ Group '{gname}': anchored to parent site "
                    f"'{site_name}' (id={site_id}, resolved during site phase)")
            if site_id is None:
                site_match = [s for s in all_sites if s.get("name") == site_name]
                if not site_match:
                    self._operation_log.append(
                        f"  Group '{gname}': parent site '{site_name}' not found")
                    return None
                site_id = site_match[0]["id"]

            # ── Inspect the source group from the backup ──
            src_grp = node.get("group", {}) or {}
            src_type = src_grp.get("type")
            src_filter_id = src_grp.get("filterId") \
                or (src_grp.get("filter") or {}).get("id")
            # Resolve the filter's NAME from (a) the group payload itself,
            # then (b) the per-restore source filter-id→name map built from
            # other nodes' saved-filter backups. This covers both new
            # backups (filterName populated) and older ones (only filterId).
            src_filter_name = (src_grp.get("filterName")
                               or (src_grp.get("filter") or {}).get("name"))
            if not src_filter_name and src_filter_id:
                src_filter_name = (getattr(self, "_src_filter_id_to_name", {})
                                   .get(str(src_filter_id)))

            is_dynamic_source = (src_type == "dynamic"
                                 or bool(src_filter_id)
                                 or bool(src_filter_name))

            # ── Look up matching destination saved filter by NAME ──
            # Cache per site so repeated group lookups don't re-hit /filters.
            dest_filter_id = None
            if is_dynamic_source and src_filter_name:
                cache = getattr(self, "_dest_filter_cache", {})
                site_cache = cache.get(site_id)
                if site_cache is None:
                    try:
                        site_cache = {
                            f.get("name"): f.get("id")
                            for f in api.get_saved_filters(
                                {"siteIds": site_id})
                            if f.get("name") and f.get("id")
                        }
                    except Exception as e:
                        site_cache = {}
                        self._operation_log.append(
                            f"  ⚠ Group '{gname}': could not list dest "
                            f"filters ({e})")
                    cache[site_id] = site_cache
                dest_filter_id = site_cache.get(src_filter_name)

            # ── Build the desired payload (no stale source IDs) ──
            allowed = {"name", "rank", "description"}
            desired = {k: v for k, v in src_grp.items()
                       if k in allowed and v is not None}
            desired["name"] = gname
            # IMPORTANT: always create with inherits=True. S1 rejects
            # `inherits=False` on group create unless a full `policy` body
            # is supplied in the same call (error code 4000010:
            # "Policy should be delivered if it is not inherited"). The
            # per-node policy-restore step that runs right after this
            # decouples + pushes the real policy when the source had a
            # custom policy, so the final state still matches the source.
            desired["inherits"] = True
            if is_dynamic_source and dest_filter_id:
                desired["type"] = "dynamic"
                desired["filterId"] = dest_filter_id
            elif src_type == "pinned":
                # Preserve the Pinned group type from the source. S1 POST
                # /groups accepts `type=pinned` directly; the group is
                # created without any pinned agents (agents don't migrate),
                # but the group itself carries the Pinned label so the
                # destination matches the source's classification.
                desired["type"] = "pinned"

            _p(f"looking up group '{gname}'…")
            all_groups = api.get_groups(params={"siteIds": site_id})
            grp_match = [g for g in all_groups if g.get("name") == gname]

            # ── Existing group: overwrite when source differs ──
            if grp_match:
                existing = grp_match[0]
                existing_id = existing["id"]
                existing_type = existing.get("type")
                existing_filter_id = existing.get("filterId") \
                    or (existing.get("filter") or {}).get("id")

                # Diagnostic — without this it's impossible to tell why a
                # particular static group isn't being flipped to dynamic.
                self._operation_log.append(
                    f"  · Group '{gname}' (id={existing_id}) compare: "
                    f"src[type={src_type!r}, filterId={src_filter_id!r}, "
                    f"filterName={src_filter_name!r}, "
                    f"dynamic={is_dynamic_source}] "
                    f"vs dest[type={existing_type!r}, "
                    f"filterId={existing_filter_id!r}] "
                    f"resolved dest_filter_id={dest_filter_id!r}")

                drift = {}
                # IMPORTANT: PUT /groups/{id} on this S1 version does NOT
                # accept a `type` field — sending it returns:
                #   "data: type: Unknown field (code 4000010)"
                # S1 infers `type=dynamic` from the *presence* of filterId,
                # and `type=static` from its absence. So we only send the
                # filterId on the conversion.
                if is_dynamic_source and dest_filter_id:
                    if existing_type != "dynamic" \
                            or existing_filter_id != dest_filter_id:
                        drift["filterId"] = dest_filter_id
                elif src_type == "pinned" and existing_type != "pinned":
                    # Source is a Pinned group but destination is static
                    # (or dynamic). Try the dedicated convert endpoint
                    # chain in S1API.move_group_to_pinned. Verify by
                    # re-reading the group after the call — some S1
                    # versions return 200 but silently no-op the change.
                    try:
                        api.move_group_to_pinned(existing_id)
                        # Verify
                        verify = api.get_groups(
                            params={"siteIds": site_id})
                        after = next((g for g in verify
                                      if g.get("id") == existing_id), {})
                        after_type = after.get("type")
                        if after_type == "pinned":
                            self._operation_log.append(
                                f"  📌 Converted group '{gname}' "
                                f"(id={existing_id}) → pinned "
                                f"(matched source type)")
                        else:
                            self._operation_log.append(
                                f"  ⚠ move-to-pinned returned 200 for "
                                f"'{gname}' but the group is still "
                                f"type={after_type!r}. S1 may not "
                                f"support converting an empty group to "
                                f"pinned on this tenant — Pinned groups "
                                f"require at least one pinned agent.")
                    except Exception as e:
                        sc = getattr(e, "status_code", 0)
                        detail = getattr(e, "detail", str(e))
                        self._operation_log.append(
                            f"  ⚠ Could not convert group '{gname}' to "
                            f"pinned (HTTP {sc}): {detail}. "
                            f"The destination group keeps "
                            f"type={existing_type!r}.")
                elif is_dynamic_source and not dest_filter_id:
                    # Source is dynamic but the matching filter doesn't
                    # exist on the destination yet. DO NOT downgrade the
                    # destination group to static — that would discard work
                    # the operator may have already done. Tell them what
                    # to do and skip the update.
                    self._operation_log.append(
                        f"  ⚠ Group '{gname}' is dynamic on source but "
                        f"saved filter '{src_filter_name or src_filter_id}' "
                        f"is missing on destination site — leaving the "
                        f"existing group untouched. Restore "
                        f"`saved_filters` first, then re-run.")
                # Description / rank can be safely synced regardless of
                # dynamic/static — but skip empty-string vs None drift,
                # which is cosmetic noise from S1 returning None for
                # unset fields while the source carries "".
                for k in ("description", "rank"):
                    if k not in desired:
                        continue
                    src_val = desired[k]
                    dest_val = existing.get(k)
                    if src_val == dest_val:
                        continue
                    if (src_val in ("", None)) and (dest_val in ("", None)):
                        continue
                    drift[k] = src_val

                if drift:
                    # Send a coherent payload (name + the drifted fields).
                    # Some S1 versions reject partial PUTs to /groups/{id}
                    # when changing `type` without `name` also present.
                    payload = {"name": gname, **drift}
                    _p(f"overwriting group '{gname}' → {list(drift.keys())}")
                    try:
                        api.update_group(existing_id, payload)
                        # Verify the change actually took — S1 occasionally
                        # returns 200 but silently no-ops type conversion
                        # when the group has agents already assigned.
                        try:
                            verify = api.get_groups(
                                params={"siteIds": site_id})
                            after = next((g for g in verify
                                          if g.get("id") == existing_id), {})
                            self._operation_log.append(
                                f"  ↻ Overwrote existing group '{gname}' "
                                f"(id={existing_id}) → "
                                f"{', '.join(f'{k}={v}' for k, v in drift.items())} "
                                f"| post-state: type={after.get('type')!r}, "
                                f"filterId={(after.get('filterId') or (after.get('filter') or {}).get('id'))!r}")
                        except Exception:
                            self._operation_log.append(
                                f"  ↻ Overwrote existing group '{gname}' "
                                f"(id={existing_id}): "
                                f"{', '.join(f'{k}={v}' for k, v in drift.items())}")
                    except Exception as e:
                        detail = getattr(e, "detail", str(e))
                        self._operation_log.append(
                            f"  ✗ Failed to overwrite group '{gname}': "
                            f"{detail}")
                        cli_log(f"Group '{gname}' update error: {detail}",
                                "error")
                else:
                    _p(f"found group → id={existing_id} "
                       f"(already matches source)")
                return existing_id

            # ── No existing group: create ──
            if is_dynamic_source and not dest_filter_id:
                self._operation_log.append(
                    f"  ⚠ Group '{gname}': source is dynamic but saved "
                    f"filter '{src_filter_name or src_filter_id}' is missing "
                    f"on destination — creating as STATIC. Restore "
                    f"`saved_filters` first, then re-run to upgrade it.")
            _p(f"creating group '{gname}'…")
            try:
                resp = api.create_group(site_id, desired)
                d = resp.get("data", {})
                new_id = d.get("id")
                if new_id:
                    kind = ("dynamic"
                            if (is_dynamic_source and dest_filter_id)
                            else "static")
                    self._operation_log.append(
                        f"  ✓ AUTO-CREATED {kind} group '{gname}' → id={new_id}")
                    return new_id
                self._operation_log.append(
                    f"  Group '{gname}' create returned no ID: {resp}")
            except Exception as e:
                detail = getattr(e, "detail", str(e))
                self._operation_log.append(
                    f"  ✗ Group '{gname}' create failed: {detail}")
                cli_log(f"Group '{gname}' create error: {detail}", "error")
            return None

        return None

    def _detect_dest_sku(self, api, acct_id):
        """Detect the destination account's available SKU/bundle."""
        try:
            accts = api.get_accounts()
            acct = next((a for a in accts if a.get("id") == acct_id), None)
            if not acct:
                return None
            # check licenses.bundles
            bundles = acct.get("licenses", {}).get("bundles", [])
            if bundles:
                return bundles[0].get("name", "").capitalize() or None
            # check legacy skus
            skus = acct.get("skus", [])
            if skus:
                return skus[0].get("type", "").capitalize() or None
        except Exception:
            pass
        return None

    def _ask_sku_fix(self, error_msg, dest_sku):
        """Ask user if they want to fix the SKU mismatch. Runs on main thread."""
        import threading
        result = [False]
        event = threading.Event()

        def _ask():
            r = messagebox.askyesno(
                "⚠️ License Bundle Mismatch",
                f"Site creation failed:\n{error_msg}\n\n"
                f"The destination account uses '{dest_sku}' bundle.\n\n"
                f"Do you want to automatically change all license/SKU "
                f"references in the backup data to '{dest_sku}' and retry?\n\n"
                f"This will update suite, sku, and bundle names in all "
                f"nodes of the loaded backup.")
            result[0] = r
            event.set()

        self.after(0, _ask)
        event.wait(timeout=60)
        return result[0]

    def _fix_sku_in_backup(self, dest_sku):
        """Replace all SKU/suite/bundle references in the loaded backup data."""
        if not self.backup_data:
            return
        count = 0
        sku_lower = dest_sku.lower()
        for node in self.backup_data:
            # fix site object
            site = node.get("site", {})
            if site:
                if site.get("sku") and site["sku"].lower() != sku_lower:
                    site["sku"] = dest_sku
                    count += 1
                if site.get("suite") and site["suite"].lower() != sku_lower:
                    site["suite"] = dest_sku
                    count += 1
                # fix nested licenses.bundles
                for b in site.get("licenses", {}).get("bundles", []):
                    if b.get("name") and b["name"].lower() != sku_lower:
                        b["name"] = sku_lower
                        count += 1
                # fix legacy skus
                for s in site.get("skus", []):
                    if s.get("type") and s["type"].lower() != sku_lower:
                        s["type"] = dest_sku
                        count += 1
            # fix account object
            acct = node.get("account", {})
            if acct:
                for b in acct.get("licenses", {}).get("bundles", []):
                    if b.get("name") and b["name"].lower() != sku_lower:
                        b["name"] = sku_lower
                        count += 1
                for s in acct.get("skus", []):
                    if s.get("type") and s["type"].lower() != sku_lower:
                        s["type"] = dest_sku
                        count += 1
        self._operation_log.append(
            f"  ✓ Fixed {count} SKU references → '{dest_sku}'")
        cli_log(f"Fixed {count} SKU/license references → '{dest_sku}'",
                "success")

    def _export(self):
        if not self._report_nodes and not self._operation_log:
            cli_log("No restore data to export.", "warning")
            return
        self._generate_restore_report()

    def _show_errors_dialog(self):
        """Open a window that groups every restore failure by error type,
        shows a plain-English explanation, and lets the user copy the
        bundle to clipboard to send to support."""
        import tkinter as tk

        # ── 1. Collect & group failures ──
        groups: dict = {}  # what -> {"items": [...], "first_expl": dict}
        for node in getattr(self, "_report_nodes", []):
            for fi in node.get("failed_items", []):
                detail = fi.get("error", "") or ""
                label = fi.get("element", "?")
                # Try to recover an HTTP code from the message tail
                sc = 0
                m = _re.search(r"→\s*(\d{3})", detail)
                if m:
                    sc = int(m.group(1))
                expl = explain_error(label, detail, sc)
                key = expl["what"]
                grp = groups.setdefault(key, {
                    "items": [], "expl": expl,
                })
                grp["items"].append({
                    "path": node.get("path", "?"),
                    "name": fi.get("name", "?"),
                    "raw":  detail,
                })

        if not groups:
            messagebox.showinfo(
                "No failures",
                "The last restore completed without any element failures. 🎉")
            return

        # ── 2. Build the support-bundle text (always available to copy) ──
        meta = getattr(self, "_report_meta", {})
        bundle_lines = [
            "S1 Command Center — Restore error bundle",
            f"Source console:      {meta.get('source_url', '?')}",
            f"Destination console: {meta.get('dest_url', '?')}",
            f"Started:             {meta.get('start_time', '?')}",
            f"Finished:            {meta.get('end_time', '?')}",
            f"Tool version:        v1.5.0",
            "",
            f"{sum(len(g['items']) for g in groups.values())} item(s) "
            f"failed across {len(groups)} error type(s):",
            "",
        ]
        for what, grp in groups.items():
            expl = grp["expl"]
            bundle_lines.append(f"── {what} ({len(grp['items'])} item"
                                f"{'s' if len(grp['items']) != 1 else ''}) "
                                f"[{expl['severity']}]")
            bundle_lines.append(f"   Why: {expl['why']}")
            bundle_lines.append(f"   Fix: {expl['fix']}")
            for it in grp["items"][:10]:
                bundle_lines.append(
                    f"   - {it['path']} / {it['name']}  →  {it['raw']}")
            if len(grp["items"]) > 10:
                bundle_lines.append(
                    f"   …and {len(grp['items']) - 10} more")
            bundle_lines.append("")
        bundle_text = "\n".join(bundle_lines)

        # ── 3. Build the modal window ──
        win = ctk.CTkToplevel(self)
        win.title("Restore Errors — Explained")
        win.geometry("980x680")
        win.transient(self.winfo_toplevel())
        try:
            win.grab_set()
        except Exception:
            pass

        # header strip
        hdr = ctk.CTkFrame(win, fg_color=CARD_ELEVATED, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🛟  Restore Errors — Explained",
                     font=(UI_FONT, 18, "bold"),
                     text_color=WARN).pack(side="left", padx=20, pady=14)
        total_items = sum(len(g["items"]) for g in groups.values())
        ctk.CTkLabel(hdr,
                     text=f"{len(groups)} error type(s) · "
                          f"{total_items} item(s) affected",
                     font=(UI_FONT, 12), text_color=TEXT_MUTED
                     ).pack(side="left", padx=8)

        def _copy(text: str, btn=None):
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.update()
                if btn is not None:
                    btn.configure(text="Copied ✓")
                    btn.after(1500,
                              lambda: btn.configure(text="📋 Copy"))
            except Exception as e:
                cli_log(f"Clipboard error: {e}", "error")

        # top action row — copy full bundle
        topbar = ctk.CTkFrame(win, fg_color="transparent")
        topbar.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(topbar,
                     text="Can't fix something yourself? Click below to "
                          "copy a full bundle and send it to SentinelOne "
                          "Support (or the developer).",
                     font=(UI_FONT, 12), text_color=TEXT_MUTED,
                     wraplength=700, justify="left").pack(side="left")
        copy_all_btn = ctk.CTkButton(
            topbar, text="📋 Copy ALL errors", height=34,
            fg_color=WARN, hover_color=WARN_HOVER,
            font=(UI_FONT, 12, "bold"))
        copy_all_btn.configure(
            command=lambda: _copy(bundle_text, copy_all_btn))
        copy_all_btn.pack(side="right", padx=(8, 0))

        # scrollable list of error groups
        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        sev_colors = {
            "info":    ("#3498db", "ℹ️"),
            "warning": ("#e67e22", "⚠️"),
            "error":   ("#e94560", "✗"),
        }

        for what, grp in groups.items():
            expl = grp["expl"]
            sev_color, sev_icon = sev_colors.get(expl["severity"],
                                                  ("#888", "•"))
            card = ctk.CTkFrame(body, fg_color=CARD_ELEVATED, corner_radius=10)
            card.pack(fill="x", pady=6, padx=2)

            # title row
            trow = ctk.CTkFrame(card, fg_color="transparent")
            trow.pack(fill="x", padx=14, pady=(12, 4))
            ctk.CTkLabel(trow,
                         text=f"{sev_icon}  {what}",
                         font=(UI_FONT, 14, "bold"),
                         text_color=sev_color).pack(side="left")
            ctk.CTkLabel(trow,
                         text=f"{len(grp['items'])} item"
                              f"{'s' if len(grp['items']) != 1 else ''}",
                         font=(UI_FONT, 11),
                         text_color=TEXT_MUTED).pack(side="left", padx=(10, 0))

            grp_text = (
                f"[{what}]\n"
                f"Why: {expl['why']}\n"
                f"Fix: {expl['fix']}\n\n"
                + "\n".join(
                    f"- {it['path']} / {it['name']}  →  {it['raw']}"
                    for it in grp["items"]))
            copy_grp_btn = ctk.CTkButton(
                trow, text="📋 Copy", width=80, height=26,
                fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                font=(UI_FONT, 11))
            copy_grp_btn.configure(
                command=lambda t=grp_text, b=copy_grp_btn: _copy(t, b))
            copy_grp_btn.pack(side="right")

            # explanation body
            for label, text in (
                    ("Why this happens",  expl["why"]),
                    ("What to do",        expl["fix"])):
                ctk.CTkLabel(card, text=label,
                             font=(UI_FONT, 11, "bold"),
                             text_color=TEXT_MUTED
                             ).pack(anchor="w", padx=14, pady=(8, 0))
                ctk.CTkLabel(card, text=text,
                             font=(UI_FONT, 12),
                             text_color=TEXT,
                             wraplength=880, justify="left"
                             ).pack(anchor="w", padx=14, pady=(0, 2))

            # collapsible item list
            sample_count = min(5, len(grp["items"]))
            ctk.CTkLabel(card,
                         text=f"Affected items (showing {sample_count}"
                              f" of {len(grp['items'])}):",
                         font=(UI_FONT, 11, "bold"),
                         text_color=TEXT_MUTED
                         ).pack(anchor="w", padx=14, pady=(10, 0))
            for it in grp["items"][:sample_count]:
                ctk.CTkLabel(card,
                             text=f"• {it['path']}  →  {it['name']}",
                             font=(MONO_FONT, 11),
                             text_color=TEXT_MUTED,
                             wraplength=880, justify="left"
                             ).pack(anchor="w", padx=22, pady=0)
            if len(grp["items"]) > sample_count:
                ctk.CTkLabel(card,
                             text=f"… +{len(grp['items']) - sample_count}"
                                  f" more (use 'Copy' for the full list)",
                             font=(UI_FONT, 11, "italic"),
                             text_color=TEXT_FAINT
                             ).pack(anchor="w", padx=22, pady=(0, 8))
            else:
                ctk.CTkFrame(card, height=8,
                             fg_color="transparent").pack()

        # bottom close button
        btmbar = ctk.CTkFrame(win, fg_color="transparent")
        btmbar.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btmbar, text="Close", height=34, width=100,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      command=win.destroy).pack(side="right")

    def _generate_restore_report(self):
        """Generate a comprehensive HTML restore report."""
        meta = getattr(self, "_report_meta", {})
        nodes = getattr(self, "_report_nodes", [])
        log = self._operation_log

        # ── Compute stats ──
        total = meta.get("total_nodes", len(nodes))
        done_n = sum(1 for n in nodes if n["status"] == "done")
        err_n = sum(1 for n in nodes if n["status"] == "error")
        skip_n = total - done_n - err_n

        # count individual element results across all nodes
        elem_new = elem_exist = elem_err = 0
        for n in nodes:
            for k, v in n.get("elements", {}).items():
                sv = str(v)
                if "new" in sv:
                    try: elem_new += int(sv.split("new")[0].strip().split()[-1])
                    except Exception: pass
                if "exist" in sv:
                    try: elem_exist += int(sv.split("exist")[0].strip().split()[-1])
                    except Exception: pass
                if "err" in sv:
                    try: elem_err += int(sv.split("err")[0].strip().split()[-1])
                    except Exception: pass
                if v == "ok": elem_new += 1
                if v == "exists": elem_exist += 1
                if isinstance(v, str) and v.startswith("ERR"): elem_err += 1

        elapsed = meta.get("elapsed", "?")
        src = meta.get("source_url", "?")
        dst = meta.get("dest_url", "?")
        start = meta.get("start_time", "")[:19].replace("T", " ")
        end = meta.get("end_time", "")[:19].replace("T", " ")

        # ── Build HTML ──
        from export_utils import _CSS, _badge

        # stat cards
        stats_html = f"""<div class="stats">
          <div class="stat-card"><div class="label">Nodes Restored</div>
            <div class="value">{done_n}</div></div>
          <div class="stat-card"><div class="label">Skipped</div>
            <div class="value warn">{skip_n}</div></div>
          <div class="stat-card"><div class="label">Errors</div>
            <div class="value accent">{err_n}</div></div>
          <div class="stat-card"><div class="label">Elements Created</div>
            <div class="value">{elem_new}</div></div>
          <div class="stat-card"><div class="label">Already Existed</div>
            <div class="value warn">{elem_exist}</div></div>
          <div class="stat-card"><div class="label">Element Errors</div>
            <div class="value accent">{elem_err}</div></div>
          <div class="stat-card"><div class="label">Duration</div>
            <div class="value" style="color:#74b9ff">{elapsed}</div></div>
        </div>"""

        # connection info
        info_html = f"""<div style="background:#1a1a2e; border:1px solid #2d2d44;
          border-radius:12px; padding:20px 28px; margin-bottom:24px;">
          <table style="border:none; background:transparent;">
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Source Console</td>
                <td style="color:#e0e0e0; border:none;">{src}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Destination Console</td>
                <td style="color:#e0e0e0; border:none;">{dst}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Started</td>
                <td style="color:#e0e0e0; border:none;">{start} UTC</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Finished</td>
                <td style="color:#e0e0e0; border:none;">{end} UTC</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Elements Selected</td>
                <td style="color:#e0e0e0; border:none;">{len(meta.get('elements', []))}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Status</td>
                <td style="border:none;">{_badge('cancelled' if meta.get('cancelled') else 'finished')}</td></tr>
          </table>
        </div>"""

        # per-node detail table
        node_rows = ""
        for n in nodes:
            status = n["status"]
            scls = {"done": "badge-green", "error": "badge-red"}.get(
                status, "badge-yellow")
            path = n["path"]
            ntype = n["type"].upper()

            # build element detail cells
            elem_details = []
            for ek, ev in n.get("elements", {}).items():
                sv = str(ev)
                if sv == "ok":
                    elem_details.append(
                        f'<span class="badge badge-green">{ek} ✓</span>')
                elif sv == "exists":
                    elem_details.append(
                        f'<span class="badge badge-yellow">{ek} ≡</span>')
                elif sv.startswith("ERR"):
                    elem_details.append(
                        f'<span class="badge badge-red">{ek} ✗</span>')
                elif "new" in sv or "exist" in sv:
                    elem_details.append(
                        f'<span style="color:#aaa; font-size:12px;">'
                        f'{ek}({sv})</span>')
                else:
                    elem_details.append(
                        f'<span style="color:#888; font-size:12px;">'
                        f'{ek}:{sv}</span>')

            elem_html = " &nbsp;".join(elem_details) if elem_details else \
                '<span style="color:#555">—</span>'

            node_rows += f"""<tr>
              <td style="white-space:nowrap">{ntype}</td>
              <td>{path}</td>
              <td><span class="badge {scls}">{status}</span></td>
              <td style="max-width:500px; white-space:normal">{elem_html}</td>
            </tr>"""

        node_table = f"""<h2 style="color:#fff; margin:28px 0 12px; font-size:18px;">
          Per-Node Details</h2>
        <table><thead><tr>
          <th>Type</th><th>Path</th><th>Status</th><th>Elements</th>
        </tr></thead><tbody>{node_rows}</tbody></table>"""

        # errors section
        errors = [l for l in log if "✗" in l]
        errors_html = ""
        if errors:
            err_rows = "".join(
                f'<tr><td style="color:#e94560; font-family:Consolas,monospace;'
                f'font-size:12px; white-space:normal; border:none; '
                f'padding:6px 12px; border-bottom:1px solid #222238;">'
                f'{e.strip()}</td></tr>'
                for e in errors)
            errors_html = f"""<h2 style="color:#e94560; margin:28px 0 12px;
              font-size:18px;">Errors &amp; Warnings ({len(errors)})</h2>
            <table style="border:1px solid #3b0d1e;">
              <tbody>{err_rows}</tbody></table>"""

        # failed items detail table
        all_failed = []
        for n in nodes:
            for fi in n.get("failed_items", []):
                all_failed.append({
                    "path": n["path"],
                    "element": fi["element"],
                    "name": fi["name"],
                    "error": fi["error"],
                })
        failed_html = ""
        if all_failed:
            # Group failures by explanation 'what' so the operator sees a
            # short, deduplicated triage list instead of one row per item.
            grouped: dict = {}
            for fi in all_failed:
                detail = fi["error"] or ""
                sc = 0
                m = _re.search(r"→\s*(\d{3})", detail)
                if m:
                    sc = int(m.group(1))
                expl = explain_error(fi["element"], detail, sc)
                grouped.setdefault(expl["what"], {
                    "expl": expl, "items": [],
                })["items"].append(fi)

            sev_color = {
                "info": "#3498db", "warning": "#e67e22", "error": "#e94560",
            }
            triage_rows = ""
            for what, grp in grouped.items():
                e = grp["expl"]
                color = sev_color.get(e["severity"], "#888")
                why_html = e["why"].replace("\n", "<br>")
                fix_html = e["fix"].replace("\n", "<br>")
                triage_rows += (
                    f'<tr>'
                    f'<td style="vertical-align:top; color:{color}; '
                    f'font-weight:bold; white-space:nowrap;">{what}</td>'
                    f'<td style="vertical-align:top; color:#888; '
                    f'text-align:center;">{len(grp["items"])}</td>'
                    f'<td style="vertical-align:top; color:#ddd; '
                    f'font-size:13px;">{why_html}</td>'
                    f'<td style="vertical-align:top; color:#ddd; '
                    f'font-size:13px;">{fix_html}</td>'
                    f'</tr>'
                )

            fi_rows = ""
            for fi in all_failed:
                fi_rows += (
                    f'<tr>'
                    f'<td style="color:#aaa">{fi["path"]}</td>'
                    f'<td><span class="badge badge-red">{fi["element"]}</span></td>'
                    f'<td style="color:#fff; font-family:Consolas,monospace; '
                    f'font-size:12px; white-space:normal;">{fi["name"]}</td>'
                    f'<td style="color:#e94560; font-family:Consolas,monospace; '
                    f'font-size:11px; white-space:normal;">{fi["error"]}</td>'
                    f'</tr>')
            failed_html = f"""<h2 style="color:#fdcb6e; margin:28px 0 12px;
              font-size:18px;">🛟 Error Triage — What each error means &amp;
              how to fix it</h2>
            <p style="color:#888; font-size:13px; margin-bottom:12px;">
              Failures are grouped by error type. Open the GUI's
              <b>🛟 Explain Errors</b> button for an interactive copy-to-clipboard
              version of this table.</p>
            <table><thead><tr>
              <th style="width:200px;">Error type</th><th>#</th>
              <th>Why it happens</th><th>What to do</th>
            </tr></thead><tbody>{triage_rows}</tbody></table>

            <h2 style="color:#fdcb6e; margin:28px 0 12px;
              font-size:18px;">⚠ Items Not Restored — Manual Action Required
              ({len(all_failed)} items)</h2>
            <p style="color:#888; font-size:13px; margin-bottom:12px;">
              Raw per-item failures. Cross-reference each row with the
              triage table above for the recommended action.</p>
            <table><thead><tr>
              <th>Node Path</th><th>Element</th>
              <th>Item Name / Value</th><th>Error</th>
            </tr></thead><tbody>{fi_rows}</tbody></table>"""

        # full log
        log_lines = "".join(
            f'<div style="font-family:Consolas,monospace; font-size:11px; '
            f'color:#888; padding:1px 0;">{l}</div>'
            for l in log)
        log_html = f"""<details open style="margin-top:28px;">
          <summary style="color:#888; cursor:pointer; font-size:14px;
            margin-bottom:8px;">Full Operation Log ({len(log)} lines)</summary>
          <div style="background:#111; border-radius:8px; padding:16px;
            max-height:600px; overflow-y:auto;">{log_lines}</div>
        </details>"""

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Restore Report — S1 Command Center</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>🔄 Restore Report</h1>
  <div class="subtitle">S1 Command Center — Configuration Migration Report</div>
  <div class="meta">Generated {now} &bull; {total} nodes in backup
    &bull; {done_n} restored &bull; {elapsed}</div>
</div>
{stats_html}
{info_html}
{node_table}
{errors_html}
{failed_html}
{log_html}
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi &bull; Generated {now}</div>
</body></html>"""

        # save
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        path = filedialog.asksaveasfilename(
            title="Export Restore Report",
            initialfile=f"s1-restore-report-{ts}",
            defaultextension=".json",
            filetypes=[
                ("JSON Data", "*.json"),
                ("HTML Report", "*.html"),
            ])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".html":
            with open(path, "w") as f:
                f.write(html)
        else:
            report = {"meta": meta, "nodes": nodes, "log": log}
            with open(path, "w") as f:
                json.dump(report, f, indent=2, default=str)
        cli_log(f"Restore report exported → {os.path.basename(path)}",
                "success")
        messagebox.showinfo("Report Exported",
                            f"Restore report saved to:\n{path}")


# ═══════════════════════════════════════════════════════════════════════
#  Migration Validation Page
# ═══════════════════════════════════════════════════════════════════════

class ValidationPage(ctk.CTkFrame):
    """Post-migration validation: compares every setting on the SOURCE
    console against the DESTINATION (live ↔ live) and explains, in plain
    English, anything that still differs. Exportable as an HTML report."""

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self._cancelled = False
        self._results: list = []
        self._meta: dict = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(self, text="Migration Validation",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(
            self,
            text="Compare every setting on the SOURCE against the "
                 "DESTINATION to confirm nothing was missed after a "
                 "migration. Any difference is explained in plain English.",
            font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # ── Controls card ──
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(0, weight=1, uniform="cols")
        card.grid_columnconfigure(1, weight=1, uniform="cols")

        # Two clearly separated panels: SOURCE (left) and DESTINATION (right)
        def _scope_panel(col, title, tint, accent, url_attr, acct_attr,
                         site_attr, site_ph):
            box = ctk.CTkFrame(card, fg_color=tint, corner_radius=10)
            box.grid(row=0, column=col, sticky="nsew",
                     padx=(12, 6) if col == 0 else (6, 12), pady=12)
            box.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(box, text=title, font=(UI_FONT, 14, "bold"),
                         text_color=accent).grid(
                row=0, column=0, columnspan=2, sticky="w",
                padx=12, pady=(10, 6))

            ctk.CTkLabel(box, text="URL", font=(UI_FONT, 11),
                         text_color=TEXT_MUTED).grid(
                row=1, column=0, sticky="w", padx=(12, 8), pady=4)
            url_lbl = ctk.CTkLabel(box, text="—", font=(MONO_FONT, 12),
                                   text_color=TEXT, anchor="w")
            url_lbl.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=4)
            setattr(self, url_attr, url_lbl)

            ctk.CTkLabel(box, text="Account", font=(UI_FONT, 11),
                         text_color=TEXT_MUTED).grid(
                row=2, column=0, sticky="w", padx=(12, 8), pady=4)
            acct_e = ctk.CTkEntry(box, placeholder_text="(blank = all)",
                                  height=32)
            acct_e.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
            setattr(self, acct_attr, acct_e)

            ctk.CTkLabel(box, text="Site", font=(UI_FONT, 11),
                         text_color=TEXT_MUTED).grid(
                row=3, column=0, sticky="w", padx=(12, 8), pady=(4, 12))
            site_e = ctk.CTkEntry(box, placeholder_text=site_ph, height=32)
            site_e.grid(row=3, column=1, sticky="ew", padx=(0, 12),
                        pady=(4, 12))
            setattr(self, site_attr, site_e)

        _scope_panel(0, "📤  SOURCE", "#16241c", GREEN,
                     "_src_url_lbl", "_src_acct", "_src_site",
                     "(blank = all)")
        _scope_panel(1, "📥  DESTINATION", "#2a141b", ACCENT,
                     "_dst_url_lbl", "_dst_acct", "_dst_site",
                     "(blank = same as source)")
        # Dest account placeholder hint (created above with generic text)
        self._dst_acct.configure(placeholder_text="(blank = same as source)")

        # Shared row: levels + group filter
        shared = ctk.CTkFrame(card, fg_color="transparent")
        shared.grid(row=1, column=0, columnspan=2, sticky="ew",
                    padx=12, pady=(0, 12))
        shared.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(shared, text="Compare levels:",
                     font=(UI_FONT, 13, "bold"), text_color=TEXT_MUTED).grid(
            row=0, column=0, padx=(0, 8), sticky="w")
        lv_inner = ctk.CTkFrame(shared, fg_color="transparent")
        lv_inner.grid(row=0, column=1, sticky="w")
        self._level_vars = {}
        for lv, default in [("accounts", True), ("sites", True),
                            ("groups", True)]:
            v = ctk.BooleanVar(value=default)
            self._level_vars[lv] = v
            ctk.CTkCheckBox(lv_inner, text=lv.capitalize(), variable=v,
                            font=(UI_FONT, 12)).pack(
                side="left", padx=(0, 12))
        ctk.CTkLabel(shared, text="Group filter:", font=(UI_FONT, 13),
                     text_color=TEXT_MUTED).grid(
            row=0, column=2, padx=(20, 8), sticky="e")
        self._group_f = ctk.CTkEntry(shared, placeholder_text="(blank = all)",
                                     height=32)
        self._group_f.grid(row=0, column=3, sticky="ew")

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=20, pady=8)
        self._run_btn = ctk.CTkButton(
            btn_row, text="▶ Run Validation", height=38,
            fg_color=GREEN, hover_color=GREEN_HOVER,
            font=(UI_FONT, 14, "bold"), command=self._start)
        self._run_btn.pack(side="left")
        self._stop_btn = ctk.CTkButton(
            btn_row, text="■ Stop", height=38, width=80,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, state="disabled",
            font=(UI_FONT, 13, "bold"), command=self._stop)
        self._stop_btn.pack(side="left", padx=6)
        self._export_btn = ctk.CTkButton(
            btn_row, text="📄 Export Report", height=38, width=150,
            fg_color=BRAND, hover_color=BRAND_HOVER, state="disabled",
            font=(UI_FONT, 13, "bold"), command=self._export_report)
        self._export_btn.pack(side="left", padx=6)
        self._manifest_btn = ctk.CTkButton(
            btn_row, text="🧾 Migration Manifest", height=38, width=180,
            fg_color=BRAND, hover_color=BRAND_HOVER, state="disabled",
            font=(UI_FONT, 13, "bold"), command=self._export_manifest)
        self._manifest_btn.pack(side="left", padx=6)
        self._status_lbl = ctk.CTkLabel(btn_row, text="",
                                        font=(UI_FONT, 12),
                                        text_color=TEXT_MUTED)
        self._status_lbl.pack(side="left", padx=12)

        self.progress = ctk.CTkProgressBar(self, height=8)
        self.progress.set(0)
        self.progress.grid(row=4, column=0, sticky="ew", padx=20,
                           pady=(0, 4))

        # ── Summary bar ──
        self._summary = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        self._summary.grid(row=5, column=0, sticky="ew", padx=20, pady=4)
        self._summary_lbl = ctk.CTkLabel(
            self._summary,
            text="Connect both consoles, choose a scope, then run a "
                 "validation. Results appear below.",
            font=(UI_FONT, 12), text_color=TEXT_MUTED, anchor="w",
            justify="left", wraplength=900)
        self._summary_lbl.pack(fill="x", padx=14, pady=10)

        # ── Results ──
        self._results_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent")
        self._results_frame.grid(row=6, column=0, sticky="nsew",
                                 padx=16, pady=(0, 12))

    # ── Lifecycle ───────────────────────────────────────────────────────
    def on_show(self):
        """Refresh the read-only URL labels from the live connections."""
        src = getattr(self.app.source_api, "base_url", None)
        dst = getattr(self.app.dest_api, "base_url", None)
        self._src_url_lbl.configure(
            text=src or "(not connected)",
            text_color=TEXT if src else "#777")
        self._dst_url_lbl.configure(
            text=dst or "(not connected)",
            text_color=TEXT if dst else "#777")

    # ── UI state ────────────────────────────────────────────────────────
    def _set_running(self, running: bool):
        self._run_btn.configure(state="disabled" if running else "normal")
        self._stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self._export_btn.configure(state="disabled")
            self._manifest_btn.configure(state="disabled")

    def _stop(self):
        self._cancelled = True
        self._stop_btn.configure(state="disabled")
        self._status_lbl.configure(text="Stopping…", text_color=WARN)

    # ── Run ─────────────────────────────────────────────────────────────
    def _start(self):
        src = self.app.source_api
        dst = self.app.dest_api
        if not src or not dst:
            messagebox.showwarning(
                "Not connected",
                "Connect BOTH the SOURCE and DESTINATION consoles on the "
                "Connections page before validating.")
            return
        levels = {k: v.get() for k, v in self._level_vars.items()}
        if not any(levels.values()):
            messagebox.showwarning(
                "No levels", "Select at least one level to compare.")
            return
        group = self._group_f.get().strip()
        src_acct = self._src_acct.get().strip()
        src_site = self._src_site.get().strip()
        dst_acct = self._dst_acct.get().strip() or src_acct
        dst_site = self._dst_site.get().strip() or src_site
        src_filters = {"account": src_acct, "site": src_site, "group": group}
        dst_filters = {"account": dst_acct, "site": dst_site, "group": group}
        self._cancelled = False
        self._results = []
        self._meta = {}
        self.progress.set(0)
        self._set_running(True)
        for w in self._results_frame.winfo_children():
            w.destroy()
        self._summary_lbl.configure(
            text="Validation running…", text_color=INFO)
        self._status_lbl.configure(text="Starting…", text_color=TEXT_MUTED)
        cli_log("Starting migration validation (source vs destination)…",
                "cmd")

        def do():
            return self._run_validation(src, dst, src_filters, dst_filters,
                                        levels)

        def done(payload):
            self._results = payload["results"]
            self._meta = payload["meta"]
            self.progress.set(1)
            self._set_running(False)
            self._render_results()
            n = len(self._results)
            diffnodes = sum(1 for r in self._results
                            if r["matched"] and r["diffs"] > 0)
            missing = sum(1 for r in self._results if not r["matched"])
            identical = n - diffnodes - missing
            total_diffs = sum(r["diffs"] for r in self._results
                              if r["matched"])
            verdict = ("✓ Destination matches the source — nothing missing."
                       if (diffnodes == 0 and missing == 0)
                       else f"⚠ {total_diffs} difference(s) found across "
                            f"{diffnodes + missing} node(s) — see below.")
            scroll_hint = ("   ↓ scroll the list below for every node"
                           if n > 2 else "")
            self._summary_lbl.configure(
                text=f"{verdict}\nCompared {n} node(s):  "
                     f"{identical} identical  ·  {diffnodes} with differences "
                     f"·  {missing} missing on destination.{scroll_hint}",
                text_color=(GREEN if (diffnodes == 0 and missing == 0)
                            else WARN))
            self._status_lbl.configure(text="Done", text_color=GREEN)
            self._export_btn.configure(
                state="normal" if self._results else "disabled")
            self._manifest_btn.configure(
                state="normal" if self._results else "disabled")
            cli_log(f"Validation: {identical}/{n} identical, "
                    f"{diffnodes} differ, {missing} missing.", "success")
            self.app.log_audit(
                "validate", nodes=n, identical=identical,
                differing=diffnodes, missing=missing)

        def fail(e):
            self._set_running(False)
            self.progress.set(0)
            self._status_lbl.configure(text=f"Error: {str(e)[:50]}",
                                       text_color=ACCENT)
            self._summary_lbl.configure(
                text=f"Validation failed: {e}", text_color=ACCENT)
            cli_log(f"Validation failed: {e}", "error")

        run_async(self, do, done, fail)

    def _run_validation(self, src_api, dst_api, src_filters, dst_filters,
                        levels):
        def ui(fn):
            self.after(0, fn)

        # verify both reachable
        for api, label in [(src_api, "SOURCE"), (dst_api, "DESTINATION")]:
            try:
                api.get_my_user()
            except Exception:
                raise S1APIError(
                    f"Cannot reach the {label} console — check its "
                    f"connection on the Connections page.")

        ui(lambda: self._status_lbl.configure(
            text="Listing source scopes…", text_color=INFO))
        src_nodes = _enumerate_tree(src_api, src_filters, levels)
        ui(lambda: self._status_lbl.configure(
            text="Listing destination scopes…"))
        dst_nodes = _enumerate_tree(dst_api, dst_filters, levels)

        def keyof(t, a, s, n):
            return (t, (a or "").lower(), (s or "").lower(), (n or "").lower())

        dst_index = {
            keyof(n["type"], n["account_name"], n["site_name"], n["name"]):
            n["id"] for n in dst_nodes}

        # Build name remaps so renamed scopes (e.g. mangle rename during
        # migration) still line up. When exactly one distinct account/site
        # exists on each side, map source-name → destination-name.
        def _remap(field):
            sv = list(dict.fromkeys(
                n[field] for n in src_nodes if n.get(field)))
            dv = list(dict.fromkeys(
                n[field] for n in dst_nodes if n.get(field)))
            if len(sv) == 1 and len(dv) == 1 and sv[0] != dv[0]:
                return {sv[0].lower(): dv[0]}
            return {}

        acct_remap = _remap("account_name")
        site_remap = _remap("site_name")

        def lookup(sn):
            a = acct_remap.get((sn["account_name"] or "").lower(),
                               sn["account_name"])
            s = site_remap.get((sn["site_name"] or "").lower(),
                               sn["site_name"])
            nm = sn["name"]
            if sn["type"] == "account":
                nm = a
            elif sn["type"] == "site":
                nm = s
            return dst_index.get(keyof(sn["type"], a, s, nm))

        results = []
        total = len(src_nodes)
        for i, sn in enumerate(src_nodes):
            if self._cancelled:
                break
            ui(lambda i=i, p=sn["path"]: (
                self.progress.set(i / max(total, 1)),
                self._status_lbl.configure(
                    text=f"Comparing {i + 1}/{total}: {p}")))
            dst_id = lookup(sn)
            if dst_id is None:
                results.append({"type": sn["type"], "path": sn["path"],
                                "matched": False, "rows": [], "diffs": 0})
                continue
            # Read both sides through the shared backup reader so validation
            # compares every migrated element (not just the legacy subset).
            bp = self.app.pages.get("Backup Source")
            reader = bp._read_node if bp is not None else None
            src_data = _fetch_dest_snapshot(src_api, sn["type"], sn["id"],
                                            reader=reader)
            dst_data = _fetch_dest_snapshot(dst_api, sn["type"], dst_id,
                                            reader=reader)
            src_sum = _summarize_node_payload(src_data)
            dst_sum = _summarize_node_payload(dst_data)
            dst_by = {c: (cnt, names) for c, cnt, names in dst_sum}
            rows = []
            diffs = 0
            for cat, scnt, snames in src_sum:
                dcnt, dnames = dst_by.get(cat, (0, []))
                if scnt == 0 and dcnt == 0:
                    continue
                # Multiset diff so duplicate names (e.g. firewall rules)
                # surface the exact extra/missing items instead of a vague
                # "count differs".
                sc_ctr, dc_ctr = Counter(snames), Counter(dnames)
                missing = sorted((sc_ctr - dc_ctr).elements())
                extra = sorted((dc_ctr - sc_ctr).elements())
                if scnt == dcnt and not missing and not extra:
                    rows.append({"cat": cat, "src": scnt, "dst": dcnt,
                                 "status": "match"})
                else:
                    what, why, fix = _explain_diff(
                        cat, scnt, dcnt, missing, extra)
                    rows.append({"cat": cat, "src": scnt, "dst": dcnt,
                                 "status": "diff", "missing": missing,
                                 "extra": extra, "what": what, "why": why,
                                 "fix": fix})
                    diffs += 1

            # ── Field-level diff for singleton configs/settings/policy ──
            # These compare as 'present on both' above; upgrade a match to a
            # diff when their actual field values differ.
            from migtools import diff_config_fields
            field_cats = {
                "policy": (src_data.get("policy") or {},
                           dst_data.get("policy") or {}),
                "firewall_config": (
                    (src_data.get("firewall") or {}).get("config") or {},
                    (dst_data.get("firewall") or {}).get("config") or {}),
                "nq_config": (
                    (src_data.get("networkQuarantine") or {}).get("config") or {},
                    (dst_data.get("networkQuarantine") or {}).get("config") or {}),
                "device_control_config": (
                    (src_data.get("deviceControl") or {}).get("config") or {},
                    (dst_data.get("deviceControl") or {}).get("config") or {}),
                "settings_notifications": (
                    (src_data.get("settings") or {}).get("notifications") or {},
                    (dst_data.get("settings") or {}).get("notifications") or {}),
                "settings_sso": (
                    (src_data.get("settings") or {}).get("sso") or {},
                    (dst_data.get("settings") or {}).get("sso") or {}),
                "settings_smtp": (
                    (src_data.get("settings") or {}).get("smtp") or {},
                    (dst_data.get("settings") or {}).get("smtp") or {}),
                "settings_syslog": (
                    (src_data.get("settings") or {}).get("syslog") or {},
                    (dst_data.get("settings") or {}).get("syslog") or {}),
                "settings_ad": (
                    (src_data.get("settings") or {}).get("activeDirectory") or {},
                    (dst_data.get("settings") or {}).get("activeDirectory") or {}),
            }
            row_by_cat = {r["cat"]: r for r in rows}
            for fcat, (s_obj, d_obj) in field_cats.items():
                row = row_by_cat.get(fcat)
                if not row or row.get("status") != "match":
                    continue  # only upgrade 'present on both' rows
                fdiffs = diff_config_fields(s_obj, d_obj)
                if fdiffs:
                    changes = [f"{d['field']}: {d['src']} → {d['dst']}"
                               for d in fdiffs[:50]]
                    row["status"] = "diff"
                    row["missing"] = changes
                    row["extra"] = []
                    row["what"] = f"{len(fdiffs)} field value(s) differ"
                    row["why"] = ("the setting exists on both consoles but "
                                  "some field values differ")
                    row["fix"] = ("review the changed fields; re-restore this "
                                  "element to overwrite the destination values")
                    diffs += 1

            results.append({"type": sn["type"], "path": sn["path"],
                            "matched": True, "rows": rows, "diffs": diffs})

        meta = {
            "src_url": getattr(src_api, "base_url", "?"),
            "dst_url": getattr(dst_api, "base_url", "?"),
            "when": datetime.now(timezone.utc).isoformat(),
            "levels": [k for k, v in levels.items() if v],
            "src_filters": src_filters,
            "dst_filters": dst_filters,
            "cancelled": self._cancelled,
        }
        return {"results": results, "meta": meta}

    # ── Rendering ───────────────────────────────────────────────────────
    def _render_results(self):
        frame = self._results_frame
        for w in frame.winfo_children():
            w.destroy()
        if not self._results:
            ctk.CTkLabel(frame, text="No nodes were compared.",
                         text_color=TEXT_MUTED).pack(pady=16)
            return
        for r in self._results:
            card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=10)
            card.pack(fill="x", padx=4, pady=6)

            if not r["matched"]:
                badge, color = "✗ MISSING ON DESTINATION", ACCENT
            elif r["diffs"] == 0:
                badge, color = "✓ Identical", GREEN
            else:
                badge, color = f"⚠ {r['diffs']} difference(s)", WARN

            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(hdr, text=f"[{r['type'].upper()}]  {r['path']}",
                         font=(UI_FONT, 13, "bold"), anchor="w").pack(
                side="left")
            ctk.CTkLabel(hdr, text=badge, font=(UI_FONT, 12, "bold"),
                         text_color=color).pack(side="right")

            if not r["matched"]:
                ctk.CTkLabel(
                    card,
                    text="No destination scope with this name was found. "
                         "The account/site/group may have been renamed "
                         "during migration, or it was never created. Names "
                         "must match for a comparison.",
                    font=(UI_FONT, 11), text_color=TEXT_MUTED,
                    wraplength=860, justify="left", anchor="w").pack(
                    fill="x", padx=16, pady=(0, 10))
                continue

            diff_rows = [x for x in r["rows"] if x["status"] == "diff"]
            match_rows = [x for x in r["rows"] if x["status"] == "match"]

            if not diff_rows:
                ctk.CTkLabel(
                    card,
                    text=f"All {len(match_rows)} element group(s) match "
                         f"between source and destination.",
                    font=(UI_FONT, 11), text_color=GREEN, anchor="w").pack(
                    fill="x", padx=16, pady=(0, 10))
                continue

            def _names_line(label, names, color):
                shown = ", ".join(names[:6])
                if len(names) > 6:
                    shown += f"  (+{len(names) - 6} more)"
                ctk.CTkLabel(
                    box, text=f"{label} {shown}", font=(MONO_FONT, 11),
                    text_color=color, anchor="w", wraplength=860,
                    justify="left").pack(fill="x", padx=16, pady=(0, 2))

            for x in diff_rows:
                box = ctk.CTkFrame(card, fg_color=CONSOLE_BG, corner_radius=8)
                box.pack(fill="x", padx=12, pady=3)
                ctk.CTkLabel(
                    box,
                    text=f"{_cat_label(x['cat'])}   {x['src']} → {x['dst']}",
                    font=(UI_FONT, 12, "bold"), text_color=WARN,
                    anchor="w").pack(fill="x", padx=12, pady=(6, 2))
                if x.get("missing"):
                    _names_line("− Missing on dest:", x["missing"], "#ff7675")
                if x.get("extra"):
                    _names_line("+ Extra on dest:", x["extra"], "#fdcb6e")
                if not x.get("missing") and not x.get("extra"):
                    ctk.CTkLabel(
                        box, text=f"  {x['what']}", font=(UI_FONT, 11),
                        text_color=TEXT_MUTED, anchor="w").pack(
                        fill="x", padx=16, pady=(0, 2))
                ctk.CTkFrame(box, height=4, fg_color="transparent").pack()
            if match_rows:
                ctk.CTkLabel(
                    card,
                    text=f"✓ {len(match_rows)} other element group(s) match.",
                    font=(UI_FONT, 11), text_color=GREEN,
                    anchor="w").pack(fill="x", padx=16, pady=(2, 10))
            ctk.CTkLabel(
                card,
                text="Full item names & fix steps → Export Report",
                font=(UI_FONT, 10, "italic"), text_color=TEXT_FAINT,
                anchor="w").pack(fill="x", padx=16, pady=(0, 8))

    # ── Export ──────────────────────────────────────────────────────────
    def _export_report(self):
        if not self._results:
            cli_log("Run a validation first.", "warning")
            return
        from export_utils import _CSS

        meta, res = self._meta, self._results
        n = len(res)
        diffnodes = sum(1 for r in res if r["matched"] and r["diffs"] > 0)
        missing = sum(1 for r in res if not r["matched"])
        identical = n - diffnodes - missing
        total_diffs = sum(r["diffs"] for r in res if r["matched"])

        stats_html = f"""<div class="stats">
          <div class="stat-card"><div class="label">Nodes Compared</div>
            <div class="value" style="color:#74b9ff">{n}</div></div>
          <div class="stat-card"><div class="label">Identical</div>
            <div class="value">{identical}</div></div>
          <div class="stat-card"><div class="label">With Differences</div>
            <div class="value warn">{diffnodes}</div></div>
          <div class="stat-card"><div class="label">Missing on Dest</div>
            <div class="value accent">{missing}</div></div>
          <div class="stat-card"><div class="label">Total Differences</div>
            <div class="value warn">{total_diffs}</div></div>
        </div>"""

        when = meta.get("when", "")[:19].replace("T", " ")
        info_html = f"""<div style="background:#1a1a2e; border:1px solid #2d2d44;
          border-radius:12px; padding:20px 28px; margin-bottom:24px;">
          <table style="border:none; background:transparent;">
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Source Console</td>
                <td style="color:#e0e0e0; border:none;">{meta.get('src_url','?')}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Destination Console</td>
                <td style="color:#e0e0e0; border:none;">{meta.get('dst_url','?')}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Generated</td>
                <td style="color:#e0e0e0; border:none;">{when} UTC</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Levels</td>
                <td style="color:#e0e0e0; border:none;">{', '.join(meta.get('levels', [])) or '—'}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Source scope</td>
                <td style="color:#e0e0e0; border:none;">account: {meta.get('src_filters',{}).get('account') or 'all'} &bull; site: {meta.get('src_filters',{}).get('site') or 'all'}</td></tr>
            <tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">Destination scope</td>
                <td style="color:#e0e0e0; border:none;">account: {meta.get('dst_filters',{}).get('account') or 'all'} &bull; site: {meta.get('dst_filters',{}).get('site') or 'all'}</td></tr>
          </table>
        </div>"""

        # node status table
        node_rows = ""
        for r in res:
            if not r["matched"]:
                cls, txt = "badge-red", "missing on destination"
            elif r["diffs"] == 0:
                cls, txt = "badge-green", "identical"
            else:
                cls, txt = "badge-yellow", f"{r['diffs']} difference(s)"
            node_rows += (
                f'<tr><td style="white-space:nowrap">{r["type"].upper()}</td>'
                f'<td>{r["path"]}</td>'
                f'<td><span class="badge {cls}">{txt}</span></td></tr>')
        node_table = f"""<h2 style="color:#fff; margin:28px 0 12px; font-size:18px;">
          Node Comparison</h2>
        <table><thead><tr><th>Type</th><th>Path</th><th>Result</th></tr></thead>
        <tbody>{node_rows}</tbody></table>"""

        # differences table
        diff_rows_html = ""
        for r in res:
            if not r["matched"]:
                diff_rows_html += (
                    f'<tr><td style="color:#aaa">{r["path"]}</td>'
                    f'<td><span class="badge badge-red">scope</span></td>'
                    f'<td style="color:#888">—</td><td style="color:#888">—</td>'
                    f'<td style="color:#e94560; font-weight:bold;">Missing on destination</td>'
                    f'<td style="color:#ddd;">No destination scope with this '
                    f'name was found (renamed or not created).</td>'
                    f'<td style="color:#ddd;">Create/rename the scope, then '
                    f're-run the restore.</td></tr>')
                continue
            for x in r["rows"]:
                if x["status"] != "diff":
                    continue
                # Full, explicit item lists — every missing/extra name.
                items_html = ""
                if x.get("missing"):
                    lis = "".join(
                        f'<li style="color:#ff9a9a;">{m}</li>'
                        for m in x["missing"])
                    items_html += (
                        f'<div style="margin-bottom:6px;"><span '
                        f'style="color:#e94560; font-weight:bold;">✗ Missing '
                        f'on destination ({len(x["missing"])}):</span>'
                        f'<ul style="margin:4px 0 0 18px; padding:0;">'
                        f'{lis}</ul></div>')
                if x.get("extra"):
                    lis = "".join(
                        f'<li style="color:#ffe08a;">{e}</li>'
                        for e in x["extra"])
                    items_html += (
                        f'<div><span style="color:#fdcb6e; font-weight:bold;">'
                        f'＋ Extra on destination ({len(x["extra"])}):</span>'
                        f'<ul style="margin:4px 0 0 18px; padding:0;">'
                        f'{lis}</ul></div>')
                if not items_html:
                    items_html = '<span style="color:#888;">—</span>'
                diff_rows_html += (
                    f'<tr><td style="color:#aaa; vertical-align:top;">{r["path"]}</td>'
                    f'<td style="vertical-align:top;"><span class="badge badge-yellow">{_cat_label(x["cat"])}</span></td>'
                    f'<td style="text-align:center; vertical-align:top;">{x["src"]}</td>'
                    f'<td style="text-align:center; vertical-align:top;">{x["dst"]}</td>'
                    f'<td style="vertical-align:top; white-space:normal;">{items_html}</td>'
                    f'<td style="color:#ddd; white-space:normal; vertical-align:top;">{x["why"]}</td>'
                    f'<td style="color:#ddd; white-space:normal; vertical-align:top;">{x["fix"]}</td>'
                    f'</tr>')
        if not diff_rows_html:
            diff_section = """<h2 style="color:#00b894; margin:28px 0 12px;
              font-size:18px;">✓ No differences found</h2>
            <p style="color:#888;">The destination matches the source across
            every compared element. Nothing was missed.</p>"""
        else:
            diff_section = f"""<h2 style="color:#fdcb6e; margin:28px 0 12px;
              font-size:18px;">Differences &amp; What To Do ({total_diffs + missing})</h2>
            <p style="color:#888; font-size:13px; margin-bottom:12px;">
              Every differing item is listed by name below. Red = present on
              the source but missing on the destination; yellow = present on
              the destination but not the source.</p>
            <table><thead><tr>
              <th>Node Path</th><th>Element</th><th>Src</th><th>Dst</th>
              <th style="min-width:260px;">Item names (missing / extra)</th>
              <th>Why</th><th>What to do</th>
            </tr></thead><tbody>{diff_rows_html}</tbody></table>"""

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Migration Validation Report — S1 Command Center</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>✅ Migration Validation Report</h1>
  <div class="subtitle">S1 Command Center — Source vs Destination comparison</div>
  <div class="meta">Generated {now} &bull; {n} nodes compared
    &bull; {identical} identical &bull; {diffnodes + missing} with issues</div>
</div>
{stats_html}
{info_html}
{node_table}
{diff_section}
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi &bull; Generated {now}</div>
</body></html>"""

        ts = datetime.now().strftime("%Y%m%d-%H%M")
        path = filedialog.asksaveasfilename(
            title="Export Validation Report",
            initialfile=f"s1-validation-report-{ts}",
            defaultextension=".html",
            filetypes=[("HTML Report", "*.html"), ("JSON Data", "*.json")])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            with open(path, "w") as f:
                json.dump({"meta": meta, "results": res}, f, indent=2,
                          default=str)
        else:
            with open(path, "w") as f:
                f.write(html)
        cli_log(f"Validation report exported → {os.path.basename(path)}",
                "success")
        messagebox.showinfo("Report Exported",
                            f"Validation report saved to:\n{path}")

    def _export_manifest(self):
        """Export a structured migration manifest (JSON) plus a ready-to-post
        PSO ticket comment (Markdown). Feeds the 'done with PSO-XXX'
        ticket-closing workflow with the real validation outcome."""
        if not self._results:
            cli_log("Run a validation first.", "warning")
            return
        from export_utils import build_migration_manifest, manifest_to_pso_comment

        manifest = build_migration_manifest(self._meta, self._results)
        comment = manifest_to_pso_comment(manifest)

        ts = datetime.now().strftime("%Y%m%d-%H%M")
        path = filedialog.asksaveasfilename(
            title="Export Migration Manifest",
            initialfile=f"migration-manifest-{ts}",
            defaultextension=".json",
            filetypes=[("JSON Manifest", "*.json"),
                       ("PSO Comment (Markdown)", "*.md")])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".md":
                with open(path, "w") as f:
                    f.write(comment)
            else:
                with open(path, "w") as f:
                    json.dump(manifest, f, indent=2, default=str)
                # Also drop the PSO comment alongside the JSON for convenience.
                md_path = os.path.splitext(path)[0] + "-pso-comment.md"
                with open(md_path, "w") as f:
                    f.write(comment)
        except Exception as e:
            cli_log(f"Manifest export error: {e}", "error")
            messagebox.showerror("Export Error", str(e))
            return

        # Copy the PSO comment to the clipboard so it can be pasted straight
        # into the ticket (or handed to the Jira automation).
        try:
            self.clipboard_clear()
            self.clipboard_append(comment)
        except Exception:
            pass
        cli_log(f"Migration manifest exported → {os.path.basename(path)} "
                f"(PSO comment copied to clipboard)", "success")
        messagebox.showinfo(
            "Manifest Exported",
            f"Migration manifest saved to:\n{path}\n\n"
            f"The PSO ticket comment was copied to your clipboard.")


# ═══════════════════════════════════════════════════════════════════════
#  Agent Migration Page
# ═══════════════════════════════════════════════════════════════════════

class AgentMigrationPage(ctk.CTkFrame):
    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.agents = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Agent Migration",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Move agents from SOURCE console to DESTINATION using a registration token.",
                     font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # config card
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="Agent name filter:",
                     font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.name_filter = ctk.CTkEntry(
            card, placeholder_text="e.g. *WORKSTATION* (blank = all in scope)",
            height=32)
        self.name_filter.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(card, text="Dest reg. token:",
                     font=(UI_FONT, 13)).grid(
            row=1, column=0, padx=12, pady=8, sticky="w")
        self.token_entry = ctk.CTkEntry(
            card, placeholder_text="Target site/group registration token",
            height=32)
        self.token_entry.grid(row=1, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(card, text="Site scope:",
                     font=(UI_FONT, 13)).grid(
            row=2, column=0, padx=12, pady=8, sticky="w")
        self.site_filter = ctk.CTkEntry(
            card, placeholder_text="(Optional) Site name on source to scope agents",
            height=32)
        self.site_filter.grid(row=2, column=1, padx=12, pady=8, sticky="ew")

        # buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=20, pady=8)
        ctk.CTkButton(btn_row, text="Preview Agents", height=36,
                      command=self._preview).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Fetch agents from SOURCE matching the filters above."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Migrate All", height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=(UI_FONT, 13, "bold"),
                      command=self._migrate).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Send a move-to-console command for all previewed agents "
                  "using the destination registration token."
                  ).pack(side="left", padx=(0, 8))
        self._verify_btn = ctk.CTkButton(
            btn_row, text="✓ Verify Move", height=36,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
            command=self._verify_migration, state="disabled")
        self._verify_btn.pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "After migrating (give agents a few minutes to re-register), "
                  "reconcile counts: did the source drop and the destination "
                  "gain the expected number of agents? Lists any stragglers."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Export Report", height=36,
                      fg_color=BRAND,
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Export agent list as HTML/Excel/JSON."
                  ).pack(side="left", padx=(0, 8))
        self.count_lbl = ctk.CTkLabel(btn_row, text="",
                                      font=(UI_FONT, 12),
                                      text_color=TEXT_MUTED)
        self.count_lbl.pack(side="left", padx=8)

        # agent list
        self.agent_list = ctk.CTkScrollableFrame(
            self, fg_color=CARD, corner_radius=12, height=120)
        self.agent_list.grid(row=4, column=0, sticky="nsew", padx=20, pady=4)

        self.log = _ConsoleProxy(self.app)

    def _read_filters(self):
        """Read widget values on the main thread (no API calls)."""
        return {
            "name": self.name_filter.get().strip(),
            "site": self.site_filter.get().strip(),
            "token": self.token_entry.get().strip(),
        }

    @staticmethod
    def _resolve_params(api, filters):
        """Build API params from pre-read filter values (safe for background thread)."""
        params = {}
        needle = filters["name"]
        if needle:
            clean = needle.replace("*", "")
            if clean:
                params["computerName__contains"] = clean
        site = filters["site"]
        if site:
            sites = api.get_sites(params={"name": site})
            if sites:
                params["siteIds"] = sites[0]["id"]
        return params

    def _preview(self):
        api = self.app.source_api
        if not api:
            messagebox.showwarning("No source", "Connect SOURCE first.")
            return
        self.log.log("Fetching agents…")
        filters = self._read_filters()

        def do():
            return api.get_agents(params=self._resolve_params(api, filters),
                                  max_items=500)

        def done(agents):
            self.agents = agents
            self.count_lbl.configure(text=f"{len(agents)} agents found")
            for w in self.agent_list.winfo_children():
                w.destroy()
            for a in agents[:100]:
                name = a.get("computerName", "?")
                aid = a.get("id", "")
                os_name = a.get("osName", "")
                row = ctk.CTkFrame(self.agent_list, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=name,
                             font=(UI_FONT, 12, "bold")).pack(
                    side="left", padx=4)
                ctk.CTkLabel(row, text=f"  {os_name}  id={aid[:12]}…",
                             font=(UI_FONT, 11),
                             text_color=TEXT_MUTED).pack(side="left")
            if len(agents) > 100:
                ctk.CTkLabel(self.agent_list,
                             text=f"… and {len(agents)-100} more",
                             text_color=TEXT_MUTED).pack(pady=4)
            self.log.log(f"Preview: {len(agents)} agents")

        run_async(self, do, done)

    def _migrate(self):
        api = self.app.source_api
        filters = self._read_filters()
        token = filters["token"]
        if not api:
            messagebox.showwarning("No source", "Connect SOURCE first.")
            return
        if not token:
            messagebox.showwarning("Missing", "Enter a registration token.")
            return
        if not self.agents:
            messagebox.showwarning("No agents", "Preview agents first.")
            return
        if not messagebox.askyesno(
                "Confirm Migration",
                f"Migrate {len(self.agents)} agent(s) to the destination console?"):
            return

        self.log.log(f"Starting migration of {len(self.agents)} agents…")
        cli_log(f"Starting agent migration: {len(self.agents)} agents…", "cmd")
        scope_params = self._resolve_params(api, filters)
        dst_api = self.app.dest_api

        def do():
            # Baseline counts BEFORE moving, for later reconciliation.
            try:
                src_before = api.get_agent_count(scope_params)
            except Exception:
                src_before = None
            dst_before = None
            if dst_api is not None:
                try:
                    dst_before = dst_api.get_agent_count()
                except Exception:
                    dst_before = None
            ok_count = 0
            fail_count = 0
            for i, agent in enumerate(self.agents):
                name = agent.get("computerName", "?")
                aid = agent.get("id", "")
                try:
                    api.migrate_agent(aid, token)
                    self.after(0, lambda n=name: self.log.log(f"  ✓ {n}"))
                    ok_count += 1
                except Exception as e:
                    self.after(0, lambda n=name, err=e:
                               self.log.log(f"  ✗ {n}: {err}"))
                    fail_count += 1
            return ok_count, fail_count, src_before, dst_before

        def done(result):
            ok, fail, src_before, dst_before = result
            self.log.log(f"Migration done: {ok} OK, {fail} failed")
            self.app.set_status(f"Migrated {ok} agents")
            cli_log(f"Migration done: {ok} OK, {fail} failed", "success")
            self.app.log_audit(
                "agent_migrate", expected=ok, failed=fail,
                url=getattr(api, "base_url", ""))
            # Stash baseline for reconciliation.
            self._recon = {
                "expected": ok, "src_before": src_before,
                "dst_before": dst_before, "scope_params": scope_params,
                "dst_connected": dst_api is not None}
            self._verify_btn.configure(
                state="normal" if src_before is not None else "disabled")
            messagebox.showinfo(
                "Done",
                f"Migrated {ok} agents, {fail} failed.\n\n"
                f"Give agents a few minutes to re-register on the "
                f"destination, then click ‘Verify Move’ to reconcile.")

        run_async(self, do, done)

    def _verify_migration(self):
        """Reconcile agent counts after a migration: did the source drop and
        the destination gain the expected number of agents?"""
        recon = getattr(self, "_recon", None)
        if not recon or recon.get("src_before") is None:
            messagebox.showinfo("Nothing to verify",
                                "Run a migration first.")
            return
        api = self.app.source_api
        dst_api = self.app.dest_api
        if not api:
            messagebox.showwarning("No source", "Connect SOURCE first.")
            return
        self._verify_btn.configure(state="disabled")
        self.log.log("Reconciling agent counts…")

        def do():
            from migtools import reconcile_agents
            src_after = api.get_agent_count(recon["scope_params"])
            dst_before = recon["dst_before"]
            dst_after = dst_before
            if dst_api is not None and dst_before is not None:
                try:
                    dst_after = dst_api.get_agent_count()
                except Exception:
                    dst_after = dst_before
            r = reconcile_agents(
                recon["expected"], recon["src_before"], src_after,
                dst_before or 0, dst_after or 0)
            r["_dst_connected"] = recon["dst_connected"] and \
                dst_before is not None
            return r

        def done(r):
            self._verify_btn.configure(state="normal")
            head = ("✅ Reconciled — counts line up."
                    if r["reconciled"] else "⚠️ Discrepancy found.")
            lines = [
                head, "",
                f"Expected to move: {r['expected_moved']}",
                f"Source dropped by: {r['source_drop']}",
            ]
            if r.get("_dst_connected"):
                lines.append(f"Destination gained: {r['dest_gain']}")
            else:
                lines.append("Destination not connected — source-side check "
                             "only (connect the destination console for a "
                             "full reconciliation).")
            for issue in r["issues"]:
                lines.append(f"  • {issue}")
            self.app.log_audit(
                "agent_reconcile", reconciled=r["reconciled"],
                source_drop=r["source_drop"], dest_gain=r["dest_gain"])
            cli_log("Agent reconciliation: "
                    + ("OK" if r["reconciled"] else "; ".join(r["issues"])),
                    "success" if r["reconciled"] else "warning")
            messagebox.showinfo("Migration Reconciliation", "\n".join(lines))

        def fail(e):
            self._verify_btn.configure(state="normal")
            cli_log(f"Reconciliation failed: {e}", "error")

        run_async(self, do, done, fail)

    def _export(self):
        cols = ["computerName", "osName", "agentVersion", "id"]
        rows = [{c: a.get(c, "") for c in cols} for a in self.agents]
        stats = [{"label": "Total Agents", "value": len(rows)}]
        export_report("Agent Migration", cols, rows, stats=stats)

    def on_show(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Migration Runbook — guided, ordered workflow
# ═══════════════════════════════════════════════════════════════════════

class MigrationRunbookPage(ctk.CTkFrame):
    """A guided checklist that sequences the whole migration: each step opens
    the relevant page and tracks completion. Some steps auto-detect done;
    the rest are operator-confirmed. Keeps the workflow repeatable and
    hard to skip a step."""

    # (title, target page label, guidance, auto-detect key)
    STEPS = [
        ("Connect both consoles", "Connections",
         "Add SOURCE and DESTINATION and connect to each.", "connected"),
        ("Pre-flight check", "Restore to Dest",
         "Load the source backup, then click ✈ Pre-flight to confirm the "
         "destination is reachable, the token is valid/scoped, and the target "
         "scope exists.", None),
        ("Back up the source", "Backup Source",
         "Pick the scope + elements (or load a profile) and run the backup.",
         "backup"),
        ("Preview vs destination", "Restore to Dest",
         "Load the backup and click 🔍 Preview vs Dest — a dry run showing "
         "what would be created vs already exists. Nothing is written.", None),
        ("Restore to destination", "Restore to Dest",
         "With 📸 Snapshot first enabled (default), run the restore. The "
         "snapshot lets you ↩ Rollback if needed.", None),
        ("Validate the migration", "Migration Validation",
         "Compare SOURCE vs DESTINATION across every element.", "validated"),
        ("Manifest & close ticket", "Migration Validation",
         "Export 🧾 Migration Manifest — the PSO comment is copied to your "
         "clipboard for the ticket-closing workflow.", None),
    ]

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self._manual_done = set()      # step indices the user marked done
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text="Migration Runbook",
                     font=(UI_FONT, 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(
            self,
            text="A guided, ordered checklist for a console migration. Open "
                 "each step, do the work on that page, then mark it done.",
            font=(UI_FONT, 13), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 8))

        self._progress = ctk.CTkProgressBar(self, height=10)
        self._progress.set(0)
        self._progress.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        self._steps_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent")
        self._steps_frame.grid(row=3, column=0, sticky="nsew",
                                padx=16, pady=(0, 12))
        self._render()

    # ── completion detection ──────────────────────────────────────────
    def _auto_done(self, key) -> bool:
        if key == "connected":
            return bool(self.app.source_api and self.app.dest_api)
        if key == "backup":
            return bool(getattr(self.app, "_last_backup_path", None))
        if key == "validated":
            vp = self.app.pages.get("Migration Validation")
            return bool(getattr(vp, "_results", None))
        return False

    def _is_done(self, i, key) -> bool:
        return i in self._manual_done or self._auto_done(key)

    def _render(self):
        for w in self._steps_frame.winfo_children():
            w.destroy()
        done_count = 0
        for i, (title, target, guide, key) in enumerate(self.STEPS):
            done = self._is_done(i, key)
            auto = self._auto_done(key)
            if done:
                done_count += 1
            card = ctk.CTkFrame(self._steps_frame, fg_color=CARD,
                                corner_radius=10)
            card.pack(fill="x", padx=4, pady=5)
            card.grid_columnconfigure(1, weight=1)

            badge = "✅" if done else f"{i + 1}"
            ctk.CTkLabel(card, text=badge, width=34,
                         font=(UI_FONT, 16, "bold"),
                         text_color=GREEN if done else TEXT_MUTED).grid(
                row=0, column=0, rowspan=2, padx=(12, 6), pady=10)
            ctk.CTkLabel(card, text=title, anchor="w",
                         font=(UI_FONT, 14, "bold"),
                         text_color=TEXT if not done else GREEN).grid(
                row=0, column=1, sticky="ew", padx=4, pady=(10, 0))
            ctk.CTkLabel(card, text=guide, anchor="w", justify="left",
                         font=(UI_FONT, 11), text_color=TEXT_MUTED,
                         wraplength=620).grid(
                row=1, column=1, sticky="ew", padx=4, pady=(0, 10))

            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.grid(row=0, column=2, rowspan=2, padx=10)
            ctk.CTkButton(btns, text=f"Open ▸", width=90, height=32,
                          fg_color=BRAND, hover_color=BRAND_HOVER,
                          command=lambda t=target: self._open(t)).pack(
                side="left", padx=4)
            if auto:
                ctk.CTkLabel(btns, text="auto", width=70,
                             font=(UI_FONT, 11), text_color=GREEN).pack(
                    side="left", padx=4)
            else:
                ctk.CTkButton(
                    btns, text="✓ Done" if i in self._manual_done else "○ Mark",
                    width=84, height=32,
                    fg_color=GREEN if i in self._manual_done else NEUTRAL,
                    hover_color=GREEN_HOVER if i in self._manual_done
                    else NEUTRAL_HOVER,
                    command=lambda ii=i: self._toggle(ii)).pack(
                    side="left", padx=4)

        self._progress.set(done_count / len(self.STEPS))

    def _open(self, target):
        try:
            self.app._show(target)
        except Exception as e:
            cli_log(f"Could not open '{target}': {e}", "error")

    def _toggle(self, i):
        if i in self._manual_done:
            self._manual_done.discard(i)
        else:
            self._manual_done.add(i)
        self._render()

    def on_show(self):
        # Re-evaluate auto-detected steps each time the runbook is shown.
        self._render()
