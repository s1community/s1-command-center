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
    # ── Settings ──
    "settings_notifications",
    "settings_sso",
    "settings_smtp",
    "settings_syslog",
    "settings_ad",
    # ── Users & Roles ──
    "roles",
    "service_users",
    # ── Other ──
    "gateways",
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
    "settings_notifications": "Notification settings and email recipients",
    "settings_sso": "SSO / SAML single sign-on configuration",
    "settings_smtp": "SMTP relay settings for email notifications",
    "settings_syslog": "Syslog forwarding configuration",
    "settings_ad": "Active Directory integration settings",
    "roles": "RBAC custom role definitions (account level only)",
    "service_users": "API service user accounts (account level only)",
    "gateways": "Management proxy / gateway configurations",
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


class ProgressTable(ctk.CTkScrollableFrame):
    """Live-updating progress table for backup/restore operations."""

    STATUS_COLORS = {
        "pending":  ("#444", "#888"),
        "running":  ("#1a3a5c", "#4da6ff"),
        "done":     ("#0d3b2e", "#00b894"),
        "error":    ("#3b0d1e", "#e94560"),
        "skipped":  ("#333", "#666"),
    }

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 12)
        super().__init__(master, **kw)
        self._rows = {}
        self._row_idx = 0
        # header
        ctk.CTkLabel(self, text="Node", font=("Segoe UI", 10, "bold"),
                     text_color="#888", width=250).grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="w")
        ctk.CTkLabel(self, text="Status", font=("Segoe UI", 10, "bold"),
                     text_color="#888", width=70).grid(
            row=0, column=1, padx=4, pady=4)
        ctk.CTkLabel(self, text="Details", font=("Segoe UI", 10, "bold"),
                     text_color="#888").grid(
            row=0, column=2, padx=(4, 8), pady=4, sticky="w")
        self.grid_columnconfigure(2, weight=1)

    def clear(self):
        for widgets in self._rows.values():
            for w in widgets.values():
                w.destroy()
        self._rows = {}
        self._row_idx = 0

    def add_node(self, node_id: str, path: str, ntype: str = ""):
        """Add a pending row. Returns node_id for later updates."""
        self._row_idx += 1
        r = self._row_idx
        prefix = {"global": "●", "account": "▸",
                  "site": "  ▹", "group": "    ◦"}.get(ntype, "")
        bg, fg = self.STATUS_COLORS["pending"]

        name_lbl = ctk.CTkLabel(self, text=f"{prefix} {path}",
                                font=("Consolas", 11), text_color="#ccc",
                                anchor="w", width=250)
        name_lbl.grid(row=r, column=0, padx=(8, 4), pady=1, sticky="w")

        status_lbl = ctk.CTkLabel(self, text="pending",
                                  font=("Segoe UI", 10, "bold"),
                                  fg_color=bg, text_color=fg,
                                  corner_radius=6, width=70, height=22)
        status_lbl.grid(row=r, column=1, padx=4, pady=1)

        detail_lbl = ctk.CTkLabel(self, text="",
                                  font=("Consolas", 10), text_color="#999",
                                  anchor="w")
        detail_lbl.grid(row=r, column=2, padx=(4, 8), pady=1, sticky="w")

        self._rows[node_id] = {
            "name": name_lbl, "status": status_lbl, "detail": detail_lbl}
        return node_id

    def set_running(self, node_id: str):
        row = self._rows.get(node_id)
        if not row:
            return
        bg, fg = self.STATUS_COLORS["running"]
        row["status"].configure(text="running", fg_color=bg, text_color=fg)
        row["name"].configure(text_color="white")

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
            else:
                self._timer_lbl.configure(
                    text=f"✓ {m:02d}:{s:02d}", text_color=GREEN)
                self._status_lbl.configure(
                    text=f"Done — {len(backup_data)} nodes",
                    text_color=GREEN)
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
        nodes = []
        acct_f = filters.get("account", "").lower()
        site_f = filters.get("site", "").lower()
        group_f = filters.get("group", "").lower()
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
        node_count = 0
        for acct in accounts:
            aname = acct.get("name", "?")
            aid = acct.get("id", "")
            if not name_match(aname, acct_f):
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
            if not name_match(aname, acct_f):
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
                for grp in groups:
                    gname = grp.get("name", "?")
                    gid = grp.get("id", "")
                    if not name_match(gname, group_f):
                        continue
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

        # progress table for restore
        self.grid_rowconfigure(7, weight=1)
        self.ptable = ProgressTable(self, height=300)
        self.ptable.grid(row=7, column=0, sticky="nsew", padx=20, pady=(4, 12))

        self.log = _ConsoleProxy(self.app)
        self._timer_running = False
        self._timer_start = 0.0
        self._operation_log = []
        self._cancelled = False

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
            self._status_lbl.configure(text="Restore running…",
                                        text_color="#4da6ff")
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._export_btn.configure(state="normal")

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
                nm = node.get("account", {}).get("name", "")
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
            dest_id = self._resolve_dest_id(api, node, log)
            if dest_id is None and ntype != "global":
                # show the last logged error from _resolve_dest_id
                errs = [l for l in self._operation_log if "✗" in l or "not found" in l]
                reason = errs[-1].strip() if errs else "resolve failed"
                ui(lambda n=nid, r=reason: pt.set_error(n, r))
                skipped += 1
                continue

            scope = _scope(ntype, dest_id or "")
            restored += 1
            results = []
            failed_items = []  # collect per-item failures for report

            def _is_exists_error(exc):
                """Check if error means the item already exists."""
                sc = getattr(exc, "status_code", 0)
                msg = str(exc).lower()
                return (sc in (400, 409)
                        and any(w in msg for w in
                                ("already", "duplicate", "exists",
                                 "conflict", "unique",
                                 "filter with the given name",
                                 "hash",
                                 "rule with same name")))

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
                try:
                    fn(*a, **kw)
                    results.append((label, "ok"))
                except Exception as exc:
                    if _is_exists_error(exc):
                        results.append((label, "exists"))
                    else:
                        detail = getattr(exc, "detail", str(exc))
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
                ok = skip = fail = 0
                last_err_msg = ""
                for item in (items or []):
                    try:
                        fn(item)
                        ok += 1
                    except Exception as exc:
                        if _is_exists_error(exc):
                            skip += 1
                        else:
                            fail += 1
                            err_detail = getattr(exc, "detail",
                                                 str(exc))[:120]
                            last_err_msg = err_detail
                            failed_items.append({
                                "element": label,
                                "name": _item_id(item, label),
                                "error": err_detail,
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
                            api.create_exclusion(scope, _whitelist(item, _EXCL_FIELDS))
                            e_ok += 1
                        except Exception as exc:
                            if _is_exists_error(exc):
                                e_skip += 1
                            else:
                                e_fail += 1
                                e_last_err = getattr(exc, "detail",
                                                     str(exc))[:80]
                                failed_items.append({
                                    "element": f"excl/{etype}",
                                    "name": item.get("value", "?")[:80],
                                    "error": e_last_err,
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
                for rule in sorted_fw:
                    try:
                        cleaned = _whitelist(rule, _FW_RULE_FIELDS)
                        # avoid conflict: use os_types if present, drop osType
                        if "os_types" in cleaned and "osType" in cleaned:
                            del cleaned["osType"]
                        if "osTypes" in cleaned and "osType" in cleaned:
                            del cleaned["osType"]
                        resp = api.create_firewall_rule(scope, cleaned)
                        new_id = (resp.get("data", {}).get("id")
                                  if isinstance(resp, dict) else None)
                        if new_id:
                            new_fw_ids.append(new_id)
                        fw_ok += 1
                    except Exception as exc:
                        if _is_exists_error(exc):
                            fw_skip += 1
                        else:
                            fw_fail += 1
                            fw_last_err = getattr(exc, "detail",
                                                  str(exc))[:80]
                            failed_items.append({
                                "element": "fw-rule",
                                "name": rule.get("name", "?")[:80],
                                "error": fw_last_err,
                            })
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
                sorted_dc = sorted(dc_r,
                    key=lambda r: r.get("order", 9999))
                new_dc_ids = []
                dc_ok = dc_skip = dc_fail = 0
                for rule in sorted_dc:
                    try:
                        resp = api.create_device_control_rule(scope, _whitelist(rule, _DC_RULE_FIELDS))
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
                parts = []
                if dc_ok: parts.append(f"{dc_ok} new")
                if dc_skip: parts.append(f"{dc_skip} exist")
                if dc_fail: parts.append(f"{dc_fail} err")
                if parts:
                    results.append(("dc-rules", ", ".join(parts)))
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
                _r_bulk("overrides", ovr,
                        lambda o: api.create_config_override(_clean_for_restore(o)))

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

    def _resolve_dest_id(self, api, node, log):
        """Resolve destination ID, auto-creating sites/groups if missing."""
        ntype = node.get("type")
        npath = node.get("path", "")

        if ntype == "global":
            return None

        if ntype == "account":
            name = node.get("account", {}).get("name", "")
            accts = api.get_accounts()
            match = [a for a in accts if a.get("name") == name]
            if match:
                return match[0]["id"]
            # Accounts cannot be auto-created (requires Global/MSSP)
            return None

        if ntype == "site":
            sname = node.get("site", {}).get("name", "")
            # find parent account on destination
            path_parts = npath.strip("/").split("/")
            acct_name = path_parts[0] if path_parts else ""
            accts = api.get_accounts()
            acct_match = [a for a in accts if a.get("name") == acct_name]
            if not acct_match:
                self._operation_log.append(
                    f"  Site '{sname}': parent account '{acct_name}' not found")
                return None
            acct_id = acct_match[0]["id"]
            # search for site in that account
            all_sites = api.get_sites(params={"accountIds": acct_id})
            match = [s for s in all_sites if s.get("name") == sname]
            if match:
                return match[0]["id"]
            # auto-create the site
            create_data = {"name": sname}
            site_obj = node.get("site", {})
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
            # find parent site on destination
            path_parts = npath.strip("/").split("/")
            acct_name = path_parts[0] if len(path_parts) > 0 else ""
            site_name = path_parts[1] if len(path_parts) > 1 else ""
            # resolve account → site
            accts = api.get_accounts()
            acct_match = [a for a in accts if a.get("name") == acct_name]
            if not acct_match:
                self._operation_log.append(
                    f"  Group '{gname}': parent account '{acct_name}' not found")
                return None
            acct_id = acct_match[0]["id"]
            all_sites = api.get_sites(params={"accountIds": acct_id})
            site_match = [s for s in all_sites if s.get("name") == site_name]
            if not site_match:
                self._operation_log.append(
                    f"  Group '{gname}': parent site '{site_name}' not found")
                return None
            site_id = site_match[0]["id"]
            # search for group in that site
            all_groups = api.get_groups(params={"siteIds": site_id})
            grp_match = [g for g in all_groups if g.get("name") == gname]
            if grp_match:
                return grp_match[0]["id"]
            # auto-create the group (inherits policy from site by default)
            try:
                create_data = {"name": gname, "inherits": True}
                resp = api.create_group(site_id, create_data)
                d = resp.get("data", {})
                new_id = d.get("id")
                if new_id:
                    self._operation_log.append(
                        f"  ✓ AUTO-CREATED group '{gname}' → id={new_id}")
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
              font-size:18px;">⚠ Items Not Restored — Manual Action Required
              ({len(all_failed)} items)</h2>
            <p style="color:#888; font-size:13px; margin-bottom:12px;">
              These individual items could not be migrated automatically.
              Review each item and restore manually if needed.</p>
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
<div class="footer">S1 Command Center &bull; Generated {now}</div>
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
