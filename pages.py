"""
Backup, Restore, and Agent Migration pages.
"""
import customtkinter as ctk
import json
import os
from tkinter import filedialog, messagebox
from datetime import datetime, timezone
from typing import Optional

from app import run_async, LogBox, CARD, GREEN, ACCENT, WARN, cli_log, _ConsoleProxy, _help_btn
from export_utils import export_report
from s1_api import S1APIError

EXCL_TYPES = ["white_hash", "path", "file_type", "certificate", "browser"]

BACKUP_ELEMENTS = [
    # ── Core config ──
    "policy",
    "exclusions",
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
    # ── Other ──
    "gateways",
    "marketplace_apps",
]


ELEMENT_HELP = {
    "policy": "Endpoint protection policy (mitigation mode, engines, DV settings, etc.)",
    "exclusions": "All exclusion types: hash, path, file type, certificate, browser",
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
    "gateways": "Management proxy / gateway configurations",
    "marketplace_apps": "Inventory of installed Singularity Marketplace apps "
                       "(read-only — re-install manually on destination as "
                       "each app requires its own OAuth / credentials)",
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
        font=("Segoe UI", 13), fg_color="transparent", hover_color="#333",
        text_color="#ccc", anchor="w", height=28,
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
                        font=("Segoe UI", 10), width=20).pack(
            side="left")
        help_text = ELEMENT_HELP.get(el, "")
        if help_text:
            tip = ctk.CTkLabel(f, text="ⓘ", font=("Segoe UI", 10),
                               text_color="#666", cursor="hand2", width=16)
            tip.pack(side="left", padx=(2, 0))
            tip.bind("<Enter>", lambda e, t=help_text, w=tip:
                     w.configure(text_color="#4da6ff"))
            tip.bind("<Leave>", lambda e, w=tip:
                     w.configure(text_color="#666"))
            tip.bind("<Button-1>", lambda e, t=help_text, n=el:
                     cli_log(f"ⓘ {n}: {t}", "info"))
        elem_vars[el] = var

    # select all / deselect all
    sel_frame = ctk.CTkFrame(content, fg_color="transparent")
    sel_frame.grid(row=len(BACKUP_ELEMENTS) // 4 + 1, column=0,
                   columnspan=4, pady=(4, 4), sticky="w")
    ctk.CTkButton(sel_frame, text="Select All", width=80, height=24,
                  font=("Segoe UI", 10), fg_color="#555",
                  command=lambda: _update_all(True)
                  ).pack(side="left", padx=(0, 6))
    ctk.CTkButton(sel_frame, text="Deselect All", width=80, height=24,
                  font=("Segoe UI", 10), fg_color="#555",
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

    STATUS_COLORS = {
        "pending":  ("#444", "#888"),
        "running":  ("#1a3a5c", "#4da6ff"),
        "done":     ("#0d3b2e", "#00b894"),
        "error":    ("#3b0d1e", "#e94560"),
        "skipped":  ("#333", "#666"),
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
            self, bg=CARD, highlightthickness=0, bd=0, height=height)
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
                     font=("Segoe UI", 10, "bold"),
                     text_color="#888", width=250).grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="w")
        ctk.CTkLabel(self._inner, text="Status",
                     font=("Segoe UI", 10, "bold"),
                     text_color="#888", width=70).grid(
            row=0, column=1, padx=4, pady=4)
        ctk.CTkLabel(self._inner, text="Details",
                     font=("Segoe UI", 10, "bold"),
                     text_color="#888").grid(
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
                                font=("Consolas", 11), text_color="#ccc",
                                anchor="w")
        name_lbl.grid(row=r, column=0, padx=(8, 4), pady=1, sticky="ew")
        # Hover-tooltip: show the FULL path on mouse-over so the operator
        # can confirm what scope this row belongs to.
        self._attach_tooltip(name_lbl, path)

        status_lbl = ctk.CTkLabel(self._inner, text="pending",
                                  font=("Segoe UI", 10, "bold"),
                                  fg_color=bg, text_color=fg,
                                  corner_radius=6, width=70, height=22)
        status_lbl.grid(row=r, column=1, padx=4, pady=1)

        # wraplength=0 disables wrap on CTkLabel; pass a positive value so
        # long element-summary strings spill onto a second line instead of
        # being clipped. Re-computed on resize via _on_configure.
        detail_lbl = ctk.CTkLabel(self._inner, text="",
                                  font=("Consolas", 10), text_color="#999",
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
                background="#1f2329", foreground="#e0e0e0",
                relief="solid", borderwidth=1,
                font=("Consolas", 10), padx=6, pady=3)
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
        row["name"].configure(text_color="white")
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
        row["name"].configure(text_color="#aaa")
        if summary:
            row["detail"].configure(text=summary, text_color="#8f8")

    def set_error(self, node_id: str, msg: str = ""):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["error"]
        row["status"].configure(text="error", fg_color=bg, text_color=fg)
        if msg:
            row["detail"].configure(text=msg, text_color="#f88")

    def set_skipped(self, node_id: str, reason: str = ""):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["skipped"]
        row["status"].configure(text="skip", fg_color=bg, text_color=fg)
        row["name"].configure(text_color="#555")
        if reason:
            row["detail"].configure(text=reason, text_color="#666")

    def set_detail(self, node_id: str, text: str):
        row = self._rows.get(node_id)
        if row:
            row["detail"].configure(text=text, text_color="#aaa")


# Fields to strip from source objects before creating on destination
_STRIP_FIELDS = {
    # identifiers & timestamps
    "id", "createdAt", "updatedAt", "createdAt__gt", "createdAt__lt",
    "lastModified",
    # user references
    "creator", "creatorId", "updater", "updaterId",
    "userId", "userName", "userFullName",
    # scope references (destination scope is passed separately)
    "scope", "scopeName", "scopePath", "scopeId",
    "accountId", "accountName", "siteId", "siteName",
    "groupId", "groupName",
    # read-only computed fields
    "imported", "editable", "inAppInventory", "notRecommended",
    "generatedAlerts", "lastAlertTime", "reachedLimit",
    "statusReason", "expired", "source",
    "reportingAgents", "activeFirewallRules",
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
        "match": _re.compile(r"put /settings/sso.*→ 5\d\d|"
                             r"sso.*server could not process"),
        "what": "SSO configuration rejected by destination",
        "why":  "The destination tenant returned an HTTP 5xx when applying "
                "the SAML/SSO settings. Common causes: the destination has "
                "no SSO provisioned yet, the SAML certificate is bound to "
                "the source tenant's URL, or your token lacks the SSO "
                "edit permission.",
        "fix":  "1) Confirm SSO is enabled for the destination tenant.\n"
                "2) Re-issue the SAML cert/metadata using the destination "
                "URL.\n"
                "3) If you don't need to migrate SSO right now, uncheck "
                "the 'settings_sso' element and re-run.\n"
                "4) If it still fails, copy this error and send it to "
                "SentinelOne Support — server-side log lookup is needed.",
        "severity": "error",
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


# Whitelists for specific element types that are strict about accepted fields
_EXCL_FIELDS = {
    "type", "value", "osType", "description", "mode",
    "pathExclusionType", "actions", "includeChildren", "includeParents",
}

_BLOCKLIST_FIELDS = {
    "type", "value", "osType", "description", "sha256Value",
}

_FW_RULE_FIELDS = {
    # camelCase (API v2.1 format)
    "name", "description", "action", "direction", "protocol",
    "protocolS", "osType", "osTypes", "status", "order",
    "tag", "tagName",
    "localHost", "remoteHost", "localPort", "remotePort",
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

_TAG_FIELDS = {
    "name", "description", "type", "kind", "key", "value",
}


def _whitelist(obj: dict, allowed: set) -> dict:
    """Keep only allowed fields, strip None values to avoid 'may not be null' errors."""
    return {k: v for k, v in obj.items() if k in allowed and v is not None}


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


# ─── Diff-panel summary helpers ────────────────────────────────────────
# Used by the side-by-side DiffPanel on the Restore page. The same shape
# is produced from a backup node's `data` dict AND from a live destination
# query, so the two columns line up element-by-element.

# (category, count, top_names[])  — ordering matters: it's the row order
# the panel renders in.
def _summarize_node_payload(data: dict) -> list:
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
                        [str(i.get("value", ""))[:60] for i in items[:50]]))

    bl = (data or {}).get("restrictions") \
        or (data or {}).get("blocklist") or []
    out.append(("blocklist", len(bl),
                [str(b.get("value", ""))[:60] for b in bl[:50]]))

    fw = (data or {}).get("firewall", {}) or {}
    fw_rules = fw.get("rules") or []
    out.append(("fw-rules", len(fw_rules),
                [str(r.get("name", ""))[:60] for r in fw_rules[:50]]))
    fw_locs = fw.get("locations") or []
    out.append(("fw-locations", len(fw_locs),
                [str(l.get("name", ""))[:60] for l in fw_locs[:50]]))

    dc = (data or {}).get("deviceControl", {}) or {}
    dc_rules = dc.get("rules") or []
    out.append(("dc-rules", len(dc_rules),
                [str(r.get("ruleName") or r.get("name", ""))[:60]
                 for r in dc_rules[:50]]))

    nq = (data or {}).get("networkQuarantine", {}) or {}
    nq_rules = nq.get("rules") or []
    out.append(("nq-rules", len(nq_rules),
                [str(r.get("name", ""))[:60] for r in nq_rules[:50]]))

    dv = (data or {}).get("deepVisibility", {}) or {}
    flt = dv.get("filters") or (data or {}).get("saved_filters") or []
    out.append(("saved_filters", len(flt),
                [str(f.get("name", ""))[:60] for f in flt[:50]]))

    ovrs = ((data or {}).get("config", {}) or {}).get("overrides") or []
    out.append(("config_overrides", len(ovrs),
                [str(o.get("name", ""))[:60] for o in ovrs[:50]]))
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


def _fetch_dest_snapshot(api, ntype: str, dest_id: str) -> dict:
    """Snapshot the destination console for one node — shaped the same as
    a backup `data` dict so `_summarize_node_payload` works on both sides.
    Errors per-element are swallowed; missing keys just produce 0-count
    rows."""
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
                     font=("Segoe UI", 22, "bold")).pack(side="left")
        self._console_var = ctk.StringVar(value="SOURCE")
        ctk.CTkOptionMenu(hdr, values=["SOURCE", "DESTINATION"],
                          variable=self._console_var, width=160, height=32,
                          font=("Segoe UI", 14, "bold"),
                          command=lambda _: self._update_indicator()).pack(
            side="left", padx=(8, 0))
        self._indicator = ctk.CTkLabel(hdr, text="",
                                       font=("Segoe UI", 11),
                                       text_color=GREEN)
        self._indicator.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(self,
                     text="Reads accounts → sites → groups and saves config to a JSON file.",
                     font=("Segoe UI", 13), text_color="gray").grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # options card
        opts = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        opts.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        opts.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts, text="Levels:",
                     font=("Segoe UI", 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        lv_frame = ctk.CTkFrame(opts, fg_color="transparent")
        lv_frame.grid(row=0, column=1, padx=12, pady=8, sticky="w")
        self.level_vars = {}
        for lv in ["global", "accounts", "sites", "groups"]:
            var = ctk.BooleanVar(value=(lv != "global"))
            ctk.CTkCheckBox(lv_frame, text=lv.capitalize(), variable=var,
                            font=("Segoe UI", 12)).pack(side="left", padx=8)
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
                               font=("Segoe UI", 13))
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
            fg_color=GREEN, hover_color="#00a381",
            font=("Segoe UI", 14, "bold"),
            command=self._start)
        self._start_btn.pack(side="left", padx=(0, 4))
        self._stop_btn = ctk.CTkButton(
            btn_row, text="■ Stop", height=38, width=80,
            fg_color="#c0392b", hover_color="#e74c3c",
            font=("Segoe UI", 13, "bold"),
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Export Log", height=38,
                      fg_color="#2980b9",
                      command=self._export).pack(side="left", padx=(0, 4))
        self.progress = ctk.CTkProgressBar(btn_row, width=200)
        self.progress.pack(side="left", padx=8)
        self.progress.set(0)
        self._timer_lbl = ctk.CTkLabel(btn_row, text="",
                                        font=("Consolas", 12),
                                        text_color="#888")
        self._timer_lbl.pack(side="left", padx=(8, 0))
        self._status_lbl = ctk.CTkLabel(btn_row, text="",
                                         font=("Segoe UI", 12, "bold"),
                                         text_color="#888")
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
        self._acct_id = ""  # set by JiraPage._load_ticket for ID-based validation

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
                text=f"▶ {choice} — not connected", text_color="gray")

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
        if running:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._status_lbl.configure(text="Backup running…",
                                        text_color="#4da6ff")
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
            self.app._last_backup_path = path  # share with Restore page
            self._operation_log.append(
                f"Backup saved to {path} ({len(backup_data)} nodes, "
                f"{m}m {s}s)")
            self.progress.set(1)
            self.app.set_status(f"Backup complete → {path}")
            cli_log(f"Backup: {len(backup_data)} nodes in {m}m {s}s → {os.path.basename(path)}", "success")

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
        acct_f    = filters.get("account", "").lower()
        site_f    = filters.get("site", "").lower()
        group_f   = filters.get("group", "").lower()
        acct_id_f = getattr(self, "_acct_id", "").strip()
        pt = self.ptable

        def ui(fn):
            self.after(0, fn)

        def name_match(name, filt):
            return not filt or filt in name.lower()

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
            except Exception:
                pass
            nodes.append(node)

        # ── discover structure ──
        accounts = api.get_accounts()
        if acct_id_f:
            id_match = [a for a in accounts if str(a.get("id", "")) == acct_id_f]
            if not id_match:
                cli_log(f"⚠ Account ID {acct_id_f} not found in this console "
                        f"— verify the source connection is correct!", "error")
            else:
                cli_log(f"  ✓ Backup: account ID {acct_id_f} → "
                        f"'{id_match[0].get('name')}' confirmed", "success")
        node_count = 0
        for acct in accounts:
            aname = acct.get("name", "?")
            aid = acct.get("id", "")
            if acct_id_f:
                if str(aid) != acct_id_f:
                    continue
            elif not name_match(aname, acct_f):
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
            for site in sites:
                sname = site.get("name", "?")
                sid = site.get("id", "")
                if not name_match(sname, site_f):
                    continue
                node_count += 1
                try:
                    groups = api.get_groups(params={
                        "siteIds": sid, "sortBy": "name",
                        "sortOrder": "asc"})
                except Exception:
                    groups = []
                for grp in groups:
                    if name_match(grp.get("name", "?"), group_f):
                        node_count += 1

        # ── add all rows as pending first ──
        row_map = []  # (nid, type, path, obj, scope_id)
        idx = 0
        for acct in accounts:
            aname = acct.get("name", "?")
            aid = acct.get("id", "")
            if acct_id_f:
                if str(aid) != acct_id_f:
                    continue
            elif not name_match(aname, acct_f):
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

            for site in sites:
                sname = site.get("name", "?")
                sid = site.get("id", "")
                if not name_match(sname, site_f):
                    continue
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
                for grp in groups:
                    gname = grp.get("name", "?")
                    gid = grp.get("id", "")
                    if not name_match(gname, group_f):
                        continue
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
                return None

        # ── Core ──
        if "policy" in elements:
            try:
                data["policy"] = api.get_policy(scope_type, scope_id)
                results.append(("policy", "ok"))
            except Exception:
                results.append(("policy", "ERR"))

        if "exclusions" in elements:
            data["exclusions"] = {}
            total = 0
            for et in EXCL_TYPES:
                try:
                    items = api.get_exclusions(scope, et)
                    data["exclusions"][et] = items
                    total += len(items)
                except Exception:
                    pass
            results.append(("exclusions", total))

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
            _fetch("star", "star", api.get_star_rules, scope)

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
                    except Exception:
                        results.append((f"set-{sname[:4]}", "n/a"))
            if "settings_notifications" in elements:
                try:
                    settings["recipients"] = api.get_notification_recipients(scope)
                except Exception:
                    pass
            if settings:
                data["settings"] = settings

        # ── RBAC roles ──
        if "roles" in elements and scope_type == "account":
            _fetch("roles", "roles", api.get_roles)

        # ── Service users ──
        if "service_users" in elements and scope_type == "account":
            _fetch("serviceUsers", "svc-users", api.get_service_users,
                   params={"accountIds": scope_id})

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
        self.configure(fg_color="#0d0d1a")
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
            top, text="No file loaded", font=("Segoe UI", 12),
            text_color="gray")
        self._file_lbl.pack(side="left", fill="x", expand=True, anchor="w")
        ctk.CTkButton(top, text="Browse…", width=90, height=30,
                      fg_color="#555", hover_color="#666",
                      command=self._browse).pack(side="right")

        # filter row
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(filt, text="Show:", font=("Segoe UI", 12)).pack(
            side="left", padx=(0, 6))
        self._filter_var = ctk.StringVar(value="all")
        for val in ["all", "account", "site", "group"]:
            ctk.CTkRadioButton(filt, text=val.capitalize(),
                               variable=self._filter_var, value=val,
                               font=("Segoe UI", 12),
                               command=self._refresh).pack(
                side="left", padx=6)
        self._count_lbl = ctk.CTkLabel(filt, text="", font=("Segoe UI", 11),
                                        text_color="#888")
        self._count_lbl.pack(side="right")

        # scrollable table
        self._table = ctk.CTkScrollableFrame(
            self, fg_color=CARD, corner_radius=12)
        self._table.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for col, (txt, w) in enumerate(self._COLS):
            kw = {"text": txt, "font": ("Segoe UI", 10, "bold"),
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
                      fg_color="#555", hover_color="#666",
                      font=("Segoe UI", 11),
                      command=lambda: self._bulk_bool("unlimitedExpiration", True)).pack(
            side="left", padx=(0, 4))
        ctk.CTkButton(btns, text="∞ Exp OFF", height=32, width=90,
                      fg_color="#555", hover_color="#666",
                      font=("Segoe UI", 11),
                      command=lambda: self._bulk_bool("unlimitedExpiration", False)).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="∞ Lic ON", height=32, width=90,
                      fg_color="#555", hover_color="#666",
                      font=("Segoe UI", 11),
                      command=lambda: self._bulk_bool("unlimitedLicenses", True)).pack(
            side="left", padx=(0, 4))
        ctk.CTkButton(btns, text="∞ Lic OFF", height=32, width=90,
                      fg_color="#555", hover_color="#666",
                      font=("Segoe UI", 11),
                      command=lambda: self._bulk_bool("unlimitedLicenses", False)).pack(
            side="left", padx=(0, 4))

        # save row
        save_row = ctk.CTkFrame(self, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(save_row, text="Save to File", height=34,
                      fg_color="#2980b9", hover_color="#2471a3",
                      command=self._save).pack(side="right")
        self._status = ctk.CTkLabel(save_row, text="", font=("Segoe UI", 11),
                                     text_color="#888")
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
                text_color="white")
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
                         font=("Segoe UI", 11), width=60).grid(
                row=i, column=0, padx=4, pady=2, sticky="w")

            # col 1 — name
            ctk.CTkLabel(self._table, text=entry["name"],
                         font=("Segoe UI", 12, "bold"),
                         text_color="white").grid(
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
                ctk.CTkLabel(self._table, text="—", text_color="#444",
                             width=55).grid(
                    row=i, column=2, padx=4, pady=2, sticky="w")

            # col 3 — expiration entry
            if "expiration" in entry:
                exp_e = ctk.CTkEntry(self._table, width=130, height=26,
                                     font=("Consolas", 11))
                exp_e.insert(0, entry.get("expiration", ""))
                exp_e.grid(row=i, column=3, padx=4, pady=2, sticky="w")
                exp_e._entry_ref = entry
                exp_e.bind("<FocusOut>", lambda e, w=exp_e:
                           self._on_exp_change(w))
                rw["expiration"] = exp_e
            else:
                ctk.CTkLabel(self._table, text="—", text_color="#444",
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
                ctk.CTkLabel(self._table, text="—", text_color="#444",
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
                ctk.CTkLabel(self._table, text="—", text_color="#444",
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
                     font=("Segoe UI", 13, "bold")).pack(side="left")
        self._refresh_lbl = ctk.CTkLabel(
            hdr, text="", font=("Segoe UI", 10), text_color="#888")
        self._refresh_lbl.pack(side="right", padx=(4, 0))

        # ── Node selector ──
        self._node_var = ctk.StringVar(value="(no backup loaded)")
        self._node_menu = ctk.CTkOptionMenu(
            self, variable=self._node_var, values=["(no backup loaded)"],
            command=self._on_select_node, height=28,
            font=("Consolas", 11))
        self._node_menu.pack(fill="x", padx=8, pady=(2, 4))

        # ── Column headers ──
        col_hdr = ctk.CTkFrame(self, fg_color="transparent")
        col_hdr.pack(fill="x", padx=8, pady=(0, 2))
        col_hdr.grid_columnconfigure(0, weight=1, uniform="c")
        col_hdr.grid_columnconfigure(1, weight=1, uniform="c")
        ctk.CTkLabel(col_hdr, text="📦  BACKUP",
                     font=("Segoe UI", 11, "bold"),
                     text_color=GREEN, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=4)
        ctk.CTkLabel(col_hdr, text="🌐  DESTINATION (live)",
                     font=("Segoe UI", 11, "bold"),
                     text_color=ACCENT, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=4)

        # ── Text widgets ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        body.grid_columnconfigure(0, weight=1, uniform="c")
        body.grid_columnconfigure(1, weight=1, uniform="c")
        body.grid_rowconfigure(0, weight=1)

        self._left = tk.Text(
            body, font=("Consolas", 10), bg="#15171c", fg="#d0d0d0",
            relief="flat", borderwidth=0, wrap="none", height=18,
            insertbackground="#d0d0d0")
        self._left.grid(row=0, column=0, sticky="nsew", padx=(4, 2))
        self._right = tk.Text(
            body, font=("Consolas", 10), bg="#15171c", fg="#d0d0d0",
            relief="flat", borderwidth=0, wrap="none", height=18,
            insertbackground="#d0d0d0")
        self._right.grid(row=0, column=1, sticky="nsew", padx=(2, 4))

        for w in (self._left, self._right):
            w.tag_configure("hdr",  foreground="#9eaab8",
                            font=("Consolas", 10, "bold"))
            w.tag_configure("same", foreground="#6dbf6d")
            w.tag_configure("diff", foreground="#f0b248",
                            font=("Consolas", 10, "bold"))
            w.tag_configure("missing", foreground="#666",
                            font=("Consolas", 10, "italic"))
            w.tag_configure("identity_diff", foreground="#e94560",
                            font=("Consolas", 10, "bold"))
            w.configure(state="disabled")

        self._status = ctk.CTkLabel(
            self, text="Load a backup file and start a restore to see "
                       "side-by-side changes.",
            font=("Segoe UI", 10), text_color="#888", anchor="w")
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
                                         text_color="#666")
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
                     font=("Segoe UI", 22, "bold")).pack(side="left")
        self._console_var = ctk.StringVar(value="DESTINATION")
        ctk.CTkOptionMenu(hdr, values=["DESTINATION", "SOURCE"],
                          variable=self._console_var, width=160, height=32,
                          font=("Segoe UI", 14, "bold"),
                          command=lambda _: self._update_indicator()).pack(
            side="left", padx=(8, 0))
        self._indicator = ctk.CTkLabel(hdr, text="",
                                       font=("Segoe UI", 11),
                                       text_color=ACCENT)
        self._indicator.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(self,
                     text="Load a backup file and push configuration to the selected console.",
                     font=("Segoe UI", 13), text_color="gray").grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # file picker
        file_row = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        file_row.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        file_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(file_row, text="Backup file:",
                     font=("Segoe UI", 13)).grid(
            row=0, column=0, padx=12, pady=10, sticky="w")
        self.file_entry = ctk.CTkEntry(file_row, placeholder_text="Select a backup JSON…", height=32)
        self.file_entry.grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        ctk.CTkButton(file_row, text="Browse", width=80, height=32,
                      command=self._browse).grid(
            row=0, column=2, padx=12, pady=10)

        self.info_lbl = ctk.CTkLabel(file_row, text="",
                                     font=("Segoe UI", 12), text_color="gray")
        self.info_lbl.grid(row=1, column=0, columnspan=3, padx=12,
                           pady=(0, 8), sticky="w")

        # ── Mangle Rename & Set Target Context (collapsible) ──
        mangle_outer = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        mangle_outer.grid(row=3, column=0, sticky="ew", padx=20, pady=4)
        self._mangle_collapsed = True

        mangle_hdr = ctk.CTkButton(
            mangle_outer,
            text="▶ Structure Operations (optional)",
            font=("Segoe UI", 13), fg_color="transparent",
            hover_color="#333", text_color=WARN, anchor="w", height=32,
            command=self._toggle_mangle)
        mangle_hdr.pack(fill="x", padx=8, pady=4)
        self._mangle_toggle_btn = mangle_hdr

        self._mangle_content = ctk.CTkFrame(mangle_outer, fg_color="transparent")
        # starts collapsed — don't pack
        self._mangle_content.columnconfigure(1, weight=1)

        ctk.CTkLabel(self._mangle_content, text="Source Name:",
                     font=("Segoe UI", 13)).grid(
            row=0, column=0, padx=12, pady=4, sticky="w")
        self.mangle_src = ctk.CTkEntry(
            self._mangle_content,
            placeholder_text="e.g. Old Account/Old Site", height=32)
        self.mangle_src.grid(row=0, column=1, padx=12, pady=4, sticky="ew")

        ctk.CTkLabel(self._mangle_content, text="New Name:",
                     font=("Segoe UI", 13)).grid(
            row=1, column=0, padx=12, pady=4, sticky="w")
        self.mangle_dst = ctk.CTkEntry(
            self._mangle_content,
            placeholder_text="e.g. New Account/New Site", height=32)
        self.mangle_dst.grid(row=1, column=1, padx=12, pady=4, sticky="ew")

        mangle_btns = ctk.CTkFrame(self._mangle_content, fg_color="transparent")
        mangle_btns.grid(row=2, column=0, columnspan=2, padx=12,
                         pady=(6, 10), sticky="w")
        ctk.CTkButton(mangle_btns, text="Mangle Rename", height=34,
                      fg_color="#2980b9",
                      command=self._mangle_rename).pack(side="left", padx=(0, 8))
        ctk.CTkButton(mangle_btns, text="Set Target Context", height=34,
                      fg_color="#555",
                      command=self._set_target_context).pack(side="left", padx=(0, 8))
        self.mangle_status = ctk.CTkLabel(mangle_btns, text="",
                                          font=("Segoe UI", 11),
                                          text_color="gray")
        self.mangle_status.pack(side="left", padx=8)

        # restore scope card
        scope_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        scope_card.grid(row=4, column=0, sticky="ew", padx=20, pady=4)
        scope_card.grid_columnconfigure(1, weight=1)
        scope_card.grid_columnconfigure(3, weight=1)
        scope_card.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(scope_card, text="Restore level:",
                     font=("Segoe UI", 13, "bold"), text_color=ACCENT).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        lv_inner = ctk.CTkFrame(scope_card, fg_color="transparent")
        lv_inner.grid(row=0, column=1, columnspan=5, padx=12, pady=8, sticky="w")
        self.restore_level_vars = {}
        for lv in ["global", "accounts", "sites", "groups"]:
            var = ctk.BooleanVar(value=(lv != "global"))
            ctk.CTkCheckBox(lv_inner, text=lv.capitalize(), variable=var,
                            font=("Segoe UI", 12)).pack(side="left", padx=8)
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
                               font=("Segoe UI", 13))
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

        # buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=6, column=0, sticky="ew", padx=20, pady=8)
        self._start_btn = ctk.CTkButton(
            btn_row, text="▶ Restore Now", height=38,
            fg_color=ACCENT, hover_color="#c0392b",
            font=("Segoe UI", 14, "bold"),
            command=self._start_restore)
        self._start_btn.pack(side="left", padx=(0, 4))
        self._stop_btn = ctk.CTkButton(
            btn_row, text="■ Stop", height=38, width=80,
            fg_color="#c0392b", hover_color="#e74c3c",
            font=("Segoe UI", 13, "bold"),
            command=self._stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 8))
        self._export_btn = ctk.CTkButton(
            btn_row, text="Export Log", height=38,
            fg_color="#2980b9", command=self._export, state="disabled")
        self._export_btn.pack(side="left", padx=(0, 4))
        self._explain_btn = ctk.CTkButton(
            btn_row, text="🛟  Explain Errors", height=38,
            fg_color="#e67e22", hover_color="#d35400",
            command=self._show_errors_dialog, state="disabled")
        self._explain_btn.pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "After a restore, click this to see plain-English "
                  "explanations of every failure — what it means, why it "
                  "happened, what to do, and how to copy the error to send "
                  "to support."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Set Defaults", height=38,
                      fg_color="#8e44ad", hover_color="#9b59b6",
                      command=self._open_set_defaults).pack(side="left", padx=(0, 4))
        self.progress = ctk.CTkProgressBar(btn_row, width=200)
        self.progress.pack(side="left", padx=8)
        self.progress.set(0)
        self._timer_lbl = ctk.CTkLabel(btn_row, text="",
                                        font=("Consolas", 12),
                                        text_color="#888")
        self._timer_lbl.pack(side="left", padx=(8, 0))
        self._status_lbl = ctk.CTkLabel(btn_row, text="",
                                         font=("Segoe UI", 12, "bold"),
                                         text_color="#888")
        self._status_lbl.pack(side="left", padx=(8, 0))

        # progress table + diff panel (resizable side by side).
        # Use a tk.PanedWindow so the user can drag the divider to give
        # either side more room. PanedWindow requires its children to be
        # DIRECT Tk-path children, but CTkScrollableFrame wraps itself in
        # an internal canvas (its real Tk path is `…!canvas.!progresstable`,
        # not `…!progresstable`). So we add plain tk.Frame holders and
        # nest the actual widgets inside them.
        self.grid_rowconfigure(7, weight=1)
        import tkinter as _tk
        split = _tk.PanedWindow(
            self, orient="horizontal",
            sashwidth=8, sashrelief="raised",
            bg=CARD, bd=0, sashpad=0,
            opaqueresize=True)
        split.grid(row=7, column=0, sticky="nsew", padx=20, pady=(4, 12))

        # CRITICAL: PanedWindow doesn't constrain its children's heights —
        # without pack_propagate(False) the inner CTkScrollableFrame would
        # expand to fit all its rows (defeating the whole point of being
        # scrollable). Fixed initial height + propagate-off keeps the
        # scrollable region clipped so the scrollbar actually engages.
        left_pane = _tk.Frame(split, bg=CARD, bd=0, highlightthickness=0,
                              height=400)
        right_pane = _tk.Frame(split, bg=CARD, bd=0, highlightthickness=0,
                               height=400)
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
                text=f"▶ {choice} — not connected", text_color="gray")

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
            self.info_lbl.configure(
                text=f"Loaded {n} nodes: {summary}  ({os.path.basename(fp)})")
        except Exception as e:
            self.info_lbl.configure(text=f"Error: {e}")
            self.backup_data = None

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

    def _stop(self):
        self._cancelled = True
        self._stop_btn.configure(state="disabled")
        self._status_lbl.configure(text="Stopping…", text_color=WARN)
        cli_log("Restore stop requested — finishing current node…", "warning")

    def _set_ui_running(self, running: bool):
        if running:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._export_btn.configure(state="disabled")
            self._explain_btn.configure(state="disabled")
            self._status_lbl.configure(text="Restore running…",
                                        text_color="#4da6ff")
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._export_btn.configure(state="normal")
            # enable Explain Errors only if the last run produced any
            has_failures = any(
                n.get("failed_items")
                for n in getattr(self, "_report_nodes", []))
            self._explain_btn.configure(
                state="normal" if has_failures else "disabled")

    def _start_restore(self):
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

        elements = [k for k, v in self.restore_vars.items() if v.get()]
        scope_filters = {
            "account": self.restore_acct.get().strip().lower(),
            "site": self.restore_site.get().strip().lower(),
            "group": self.restore_group.get().strip().lower(),
        }
        import time as _time
        self.ptable.clear()
        self._operation_log = []
        self._skip_make_default_ids: set = set()  # sites created as Scenario B (no default override)
        self._report_nodes = []   # structured per-node report data
        self._report_meta = {     # report metadata
            "source_url": "",
            "dest_url": api.base_url,
            "dest_console": target,
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
        self.progress.set(0)
        self._timer_start = _time.time()
        self._timer_running = True
        self._tick_timer()
        self._set_ui_running(True)
        cli_log(f"Starting restore to {target} console ({len(self.backup_data)} nodes)…", "cmd")

        def do():
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

        def fail(e):
            self._timer_running = False
            self._set_ui_running(False)
            self._timer_lbl.configure(text="✗ failed", text_color=ACCENT)
            self._status_lbl.configure(text=f"Error: {str(e)[:40]}",
                                        text_color=ACCENT)
            cli_log(f"Restore failed: {e}", "error")

        run_async(self, do, done, fail)

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
                self._operation_log.append(
                    f"— Restore cancelled after {restored} nodes —")
                break

            ui(lambda v=(i+1)/total: self.progress.set(v * 0.95))

            # ── skip expired/deleted ──
            obj = node.get(ntype, {}) if ntype in ("account", "site") else {}
            state = obj.get("state", "active").lower()
            if state in ("expired", "deleted", "disabled"):
                ui(lambda n=nid, s=state: pt.set_skipped(n, s))
                skipped += 1
                continue

            # ── level + name filter ──
            level_map = {"global": "global", "account": "accounts",
                         "site": "sites", "group": "groups"}
            level_key = level_map.get(ntype, "")
            if level_key and not levels.get(level_key):
                ui(lambda n=nid: pt.set_skipped(n, "level unchecked"))
                skipped += 1
                continue
            if ntype == "account":
                # Prefer npath (already updated by mangle-rename) over the
                # nested name field which is NOT updated by mangle-rename.
                nm = npath.strip("/").split("/")[0]
                if acct_f and acct_f not in nm.lower():
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; continue
            elif ntype == "site":
                nm = node.get("site", {}).get("name", "")
                if site_f and site_f not in nm.lower():
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; continue
            elif ntype == "group":
                nm = node.get("group", {}).get("name", "")
                if group_f and group_f not in nm.lower():
                    ui(lambda n=nid: pt.set_skipped(n, "filtered"))
                    skipped += 1; continue

            # ── resolve destination (auto-create if needed) ──
            ui(lambda n=nid: pt.set_running(n))
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
                        detail = str(exc)[:80]
                        log(f"  ⚠ Default override failed: {detail}")
                        self._operation_log.append(
                            f"  ⚠ Default override failed: {detail}")

            scope = _scope(ntype, dest_id or "")
            restored += 1
            results = []
            failed_items = []  # collect per-item failures for report

            def _is_exists_error(exc):
                """Treat duplicate-create and scope-inheritance errors as
                benign skips rather than real failures.
                S1APIError carries the human-readable reason in `.detail`,
                while `str(exc)` is only the short 'METHOD /path → code'
                line, so we inspect both."""
                sc = getattr(exc, "status_code", 0)
                msg = (str(exc) + " " + str(getattr(exc, "detail", ""))).lower()
                exists_words = ("already", "duplicate", "exists",
                                "conflict", "unique",
                                "filter with the given name",
                                "hash",
                                "rule with same name",
                                "with same name")
                # 403 + 'decoupled scope' wording = destination group inherits
                # from its parent, so per-scope writes are blocked. Not a bug
                # — that's the intended inherited-config state.
                inherit_words = ("decoupled", "marking scope",
                                 "cannot update other settings")
                if sc in (400, 409) and any(w in msg for w in exists_words):
                    return True
                if sc == 403 and any(w in msg for w in inherit_words):
                    return True
                return False

            def _err_detail(exc):
                """Best-effort human-readable error text from an exception.
                S1APIError carries `.detail` but the API sometimes returns
                an empty body, leaving detail = ''. Fall back to str(exc)
                whenever detail is missing or blank so the user never sees
                an empty error in the report/dialog."""
                d = getattr(exc, "detail", "") or ""
                if not str(d).strip():
                    d = str(exc) or repr(exc)
                return str(d)

            def _item_id(item, label=""):
                """Extract a human-readable identifier from an item."""
                for key in ("name", "ruleName", "value", "s1ql",
                            "description", "type"):
                    v = item.get(key)
                    if v and isinstance(v, str):
                        return v[:80]
                return label

            def _r(label, fn, *a, **kw):
                """Restore helper: call fn, track ok/skip/fail."""
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

            def _r_bulk(label, items, fn):
                """Bulk restore: create items one by one, skip existing."""
                item_list = items or []
                total_items = len(item_list)
                ui(lambda n=nid, l=label, c=total_items:
                   pt.set_detail(n, f"restoring {l} (0/{c})…"))
                ok = skip = fail = 0
                last_err_msg = ""
                for idx, item in enumerate(item_list, 1):
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

            # ── Policy ──
            if "policy" in elements and data.get("policy"):
                _r("policy", api.set_policy, ntype, dest_id or "",
                   data["policy"])

            # ── Exclusions ──
            if "exclusions" in elements and data.get("exclusions"):
                e_ok = e_skip = e_fail = 0
                e_last_err = ""
                for etype, items in data["exclusions"].items():
                    for item in (items or []):
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
                parts = []
                if e_ok: parts.append(f"{e_ok} new")
                if e_skip: parts.append(f"{e_skip} exist")
                if e_fail: parts.append(f"{e_fail} err")
                if parts:
                    results.append(("excl", ", ".join(parts)))
                if e_last_err:
                    self._operation_log.append(
                        f"    ✗ excl last error: {e_last_err}")
                    cli_log(f"{npath} excl: {e_last_err}", "error")

            # ── Blocklist ──
            bl = data.get("restrictions") or data.get("blocklist") or []
            if "blocklist" in elements and bl:
                _r_bulk("blocklist", bl,
                        lambda item: api.create_restriction(scope, _whitelist(item, _BLOCKLIST_FIELDS)))

            # ── Firewall ──
            fw = data.get("firewall", {})
            if "firewall_config" in elements and (fw.get("config") or data.get("firewall_config")):
                _r("fw-cfg", api.set_firewall_config, scope,
                   fw.get("config") or data.get("firewall_config"))
            fw_r = fw.get("rules") or data.get("firewall_rules") or []
            if "firewall_rules" in elements and fw_r:
                sorted_fw = sorted(fw_r,
                    key=lambda r: r.get("order", 9999))
                new_fw_ids = []
                fw_ok = fw_skip = fw_fail = 0
                fw_last_err = ""
                fw_loc_stripped = 0
                for rule in sorted_fw:
                    cleaned = _whitelist(rule, _FW_RULE_FIELDS)
                    # avoid conflict: use os_types if present, drop osType
                    if "os_types" in cleaned and "osType" in cleaned:
                        del cleaned["osType"]
                    if "osTypes" in cleaned and "osType" in cleaned:
                        del cleaned["osType"]
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
                parts = []
                if fw_ok: parts.append(f"{fw_ok} new")
                if fw_skip: parts.append(f"{fw_skip} exist")
                if fw_fail: parts.append(f"{fw_fail} err")
                if parts:
                    results.append(("fw-rules", ", ".join(parts)))
                if fw_last_err:
                    self._operation_log.append(
                        f"    ✗ fw-rules last error: {fw_last_err}")
                    cli_log(f"{npath} fw-rules: {fw_last_err}", "error")
                if len(new_fw_ids) > 1:
                    try:
                        api.reorder_firewall_rules(scope, new_fw_ids)
                    except Exception:
                        pass

            # ── NQ ──
            nq = data.get("networkQuarantine", {})
            if "nq_config" in elements and nq.get("config"):
                _r("nq-cfg", api.set_nq_config, scope, nq["config"])
            if "nq_rules" in elements and nq.get("rules"):
                _r_bulk("nq-rules", nq["rules"],
                        lambda rule: api.create_nq_rule(scope, _clean_for_restore(rule)))

            # ── Device Control ──
            dc = data.get("deviceControl", {})
            if "device_control_config" in elements and (dc.get("config") or data.get("device_control_config")):
                _r("dc-cfg", api.set_device_control_config, scope,
                   dc.get("config") or data.get("device_control_config"))
            dc_r = dc.get("rules") or data.get("device_control_rules") or []
            if "device_control_rules" in elements and dc_r:
                # Only restore rules that actually belong to this node's scope.
                # The API returns inherited rules at every level, so without this
                # filter account-scoped rules appear inside site/group nodes and
                # would be incorrectly re-created (or silently fail) at the wrong scope.
                dc_r_scoped = [r for r in dc_r
                               if r.get("scope", "").lower() == ntype]
                if not dc_r_scoped:
                    log(f"  dc-rules: 0 rules at {ntype} scope "
                        f"({len(dc_r)} inherited rules skipped)")
                else:
                    sorted_dc = sorted(dc_r_scoped,
                                       key=lambda r: r.get("order", 9999))
                    new_dc_ids = []
                    dc_ok = dc_skip = dc_fail = 0
                    for rule in sorted_dc:
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
            tags = data.get("config", {}).get("tags", {})
            if "tags_firewall" in elements:
                ft = tags.get("firewall") or data.get("tags_firewall") or []
                if ft: _r_bulk("tags-fw", ft,
                               lambda t: api.create_tag(scope, _whitelist(t, _TAG_FIELDS)))
            if "tags_network_quarantine" in elements:
                nt = tags.get("networkQuarantine") or data.get("tags_nq") or []
                if nt: _r_bulk("tags-nq", nt,
                               lambda t: api.create_tag(scope, _whitelist(t, _TAG_FIELDS)))

            # ── STAR ──
            star = data.get("star") or data.get("star_rules") or []
            if "star_rules" in elements and star:
                def _create_star(rule):
                    cleaned = _whitelist(rule, _STAR_RULE_FIELDS)
                    # fix expired dates — set to 1 year from now
                    if cleaned.get("expiration"):
                        try:
                            from datetime import timedelta
                            exp = datetime.fromisoformat(
                                cleaned["expiration"].replace("Z", "+00:00"))
                            if exp < datetime.now(timezone.utc):
                                cleaned["expiration"] = (
                                    datetime.now(timezone.utc) + timedelta(days=365)
                                ).isoformat()
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
                _r_bulk("overrides", ovr,
                        lambda o: api.create_config_override(
                            scope, _build_override(o)))

            # ── Settings ──
            stg = data.get("settings", {})
            for skey, setter in [
                ("notifications", api.set_notification_settings),
                ("sso", api.set_sso_settings),
                ("smtp", api.set_smtp_settings),
                ("syslog", api.set_syslog_settings),
                ("activeDirectory", api.set_ad_settings),
            ]:
                if stg.get(skey):
                    _r(f"set-{skey[:4]}", setter, scope,
                       _clean_for_restore(stg[skey]))
            if stg.get("recipients"):
                _r("recipients", api.set_notification_recipients,
                   scope, stg["recipients"])

            # ── Threat Intel ──
            ti = data.get("threatIntel") or []
            if "threat_intel" in elements and ti:
                ok = fail = 0
                batch = []
                for ioc in ti:
                    batch.append(ioc)
                    if len(batch) >= 100:
                        try: api.upsert_threat_intel(scope, batch); ok += len(batch)
                        except Exception: fail += len(batch)
                        batch = []
                if batch:
                    try: api.upsert_threat_intel(scope, batch); ok += len(batch)
                    except Exception: fail += len(batch)
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
            else:
                ui(lambda n=nid, s=summary: pt.set_done(n, s))

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
            _p(f"account '{name}' not found")
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
                            # YES: map onto the existing site
                            _p(f"mapping to '{ed_name}' → id={candidate['id']}")
                            self._operation_log.append(
                                f"  ↻ Mapped '{sname}' → existing "
                                f"'{ed_name}' (id={candidate['id']})")
                            return candidate["id"]
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
                        if dest_sku and self._ask_sku_fix(detail, dest_sku):
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
            f"Tool version:        v1.3.7",
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
        hdr = ctk.CTkFrame(win, fg_color="#1a1a2e", corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🛟  Restore Errors — Explained",
                     font=("Segoe UI", 18, "bold"),
                     text_color="#fdcb6e").pack(side="left", padx=20, pady=14)
        total_items = sum(len(g["items"]) for g in groups.values())
        ctk.CTkLabel(hdr,
                     text=f"{len(groups)} error type(s) · "
                          f"{total_items} item(s) affected",
                     font=("Segoe UI", 12), text_color="#888"
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
                     font=("Segoe UI", 12), text_color="#aaa",
                     wraplength=700, justify="left").pack(side="left")
        copy_all_btn = ctk.CTkButton(
            topbar, text="📋 Copy ALL errors", height=34,
            fg_color="#e67e22", hover_color="#d35400",
            font=("Segoe UI", 12, "bold"))
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
            card = ctk.CTkFrame(body, fg_color="#1a1a2e", corner_radius=10)
            card.pack(fill="x", pady=6, padx=2)

            # title row
            trow = ctk.CTkFrame(card, fg_color="transparent")
            trow.pack(fill="x", padx=14, pady=(12, 4))
            ctk.CTkLabel(trow,
                         text=f"{sev_icon}  {what}",
                         font=("Segoe UI", 14, "bold"),
                         text_color=sev_color).pack(side="left")
            ctk.CTkLabel(trow,
                         text=f"{len(grp['items'])} item"
                              f"{'s' if len(grp['items']) != 1 else ''}",
                         font=("Segoe UI", 11),
                         text_color="#888").pack(side="left", padx=(10, 0))

            grp_text = (
                f"[{what}]\n"
                f"Why: {expl['why']}\n"
                f"Fix: {expl['fix']}\n\n"
                + "\n".join(
                    f"- {it['path']} / {it['name']}  →  {it['raw']}"
                    for it in grp["items"]))
            copy_grp_btn = ctk.CTkButton(
                trow, text="📋 Copy", width=80, height=26,
                fg_color="#555", hover_color="#777",
                font=("Segoe UI", 11))
            copy_grp_btn.configure(
                command=lambda t=grp_text, b=copy_grp_btn: _copy(t, b))
            copy_grp_btn.pack(side="right")

            # explanation body
            for label, text in (
                    ("Why this happens",  expl["why"]),
                    ("What to do",        expl["fix"])):
                ctk.CTkLabel(card, text=label,
                             font=("Segoe UI", 11, "bold"),
                             text_color="#888"
                             ).pack(anchor="w", padx=14, pady=(8, 0))
                ctk.CTkLabel(card, text=text,
                             font=("Segoe UI", 12),
                             text_color="#ddd",
                             wraplength=880, justify="left"
                             ).pack(anchor="w", padx=14, pady=(0, 2))

            # collapsible item list
            sample_count = min(5, len(grp["items"]))
            ctk.CTkLabel(card,
                         text=f"Affected items (showing {sample_count}"
                              f" of {len(grp['items'])}):",
                         font=("Segoe UI", 11, "bold"),
                         text_color="#888"
                         ).pack(anchor="w", padx=14, pady=(10, 0))
            for it in grp["items"][:sample_count]:
                ctk.CTkLabel(card,
                             text=f"• {it['path']}  →  {it['name']}",
                             font=("Consolas", 11),
                             text_color="#999",
                             wraplength=880, justify="left"
                             ).pack(anchor="w", padx=22, pady=0)
            if len(grp["items"]) > sample_count:
                ctk.CTkLabel(card,
                             text=f"… +{len(grp['items']) - sample_count}"
                                  f" more (use 'Copy' for the full list)",
                             font=("Segoe UI", 11, "italic"),
                             text_color="#666"
                             ).pack(anchor="w", padx=22, pady=(0, 8))
            else:
                ctk.CTkFrame(card, height=8,
                             fg_color="transparent").pack()

        # bottom close button
        btmbar = ctk.CTkFrame(win, fg_color="transparent")
        btmbar.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btmbar, text="Close", height=34, width=100,
                      fg_color="#555", hover_color="#777",
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
        log_html = f"""<details style="margin-top:28px;">
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
            defaultextension=".html",
            filetypes=[
                ("HTML Report", "*.html"),
                ("JSON Data", "*.json"),
            ])
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            report = {"meta": meta, "nodes": nodes, "log": log}
            with open(path, "w") as f:
                json.dump(report, f, indent=2, default=str)
        else:
            with open(path, "w") as f:
                f.write(html)
        cli_log(f"Restore report exported → {os.path.basename(path)}",
                "success")
        messagebox.showinfo("Report Exported",
                            f"Restore report saved to:\n{path}")


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
                     font=("Segoe UI", 22, "bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self,
                     text="Move agents from SOURCE console to DESTINATION using a registration token.",
                     font=("Segoe UI", 13), text_color="gray").grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # config card
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="Agent name filter:",
                     font=("Segoe UI", 13)).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")
        self.name_filter = ctk.CTkEntry(
            card, placeholder_text="e.g. *WORKSTATION* (blank = all in scope)",
            height=32)
        self.name_filter.grid(row=0, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(card, text="Dest reg. token:",
                     font=("Segoe UI", 13)).grid(
            row=1, column=0, padx=12, pady=8, sticky="w")
        self.token_entry = ctk.CTkEntry(
            card, placeholder_text="Target site/group registration token",
            height=32)
        self.token_entry.grid(row=1, column=1, padx=12, pady=8, sticky="ew")

        ctk.CTkLabel(card, text="Site scope:",
                     font=("Segoe UI", 13)).grid(
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
                      fg_color=ACCENT, hover_color="#c0392b",
                      font=("Segoe UI", 13, "bold"),
                      command=self._migrate).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Send a move-to-console command for all previewed agents "
                  "using the destination registration token."
                  ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Export Report", height=36,
                      fg_color="#2980b9",
                      command=self._export).pack(side="left", padx=(0, 4))
        _help_btn(btn_row,
                  "Export agent list as HTML/Excel/JSON."
                  ).pack(side="left", padx=(0, 8))
        self.count_lbl = ctk.CTkLabel(btn_row, text="",
                                      font=("Segoe UI", 12),
                                      text_color="gray")
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
                             font=("Segoe UI", 12, "bold")).pack(
                    side="left", padx=4)
                ctk.CTkLabel(row, text=f"  {os_name}  id={aid[:12]}…",
                             font=("Segoe UI", 11),
                             text_color="gray").pack(side="left")
            if len(agents) > 100:
                ctk.CTkLabel(self.agent_list,
                             text=f"… and {len(agents)-100} more",
                             text_color="gray").pack(pady=4)
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

        def do():
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
            return ok_count, fail_count

        def done(result):
            ok, fail = result
            self.log.log(f"Migration done: {ok} OK, {fail} failed")
            self.app.set_status(f"Migrated {ok} agents")
            cli_log(f"Migration done: {ok} OK, {fail} failed", "success")
            messagebox.showinfo("Done", f"Migrated {ok} agents, {fail} failed.")

        run_async(self, do, done)

    def _export(self):
        cols = ["computerName", "osName", "agentVersion", "id"]
        rows = [{c: a.get(c, "") for c in cols} for a in self.agents]
        stats = [{"label": "Total Agents", "value": len(rows)}]
        export_report("Agent Migration", cols, rows, stats=stats)

    def on_show(self):
        pass
