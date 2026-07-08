"""
Export utilities — generates beautiful HTML and Excel reports from table data.
"""
import json
import os
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Optional

from app import cli_log


# ═══════════════════════════════════════════════════════════════════════
#  HTML Report
# ═══════════════════════════════════════════════════════════════════════

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #0d0d1a; color: #e0e0e0; padding: 40px;
}
.header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-radius: 16px; padding: 32px 40px; margin-bottom: 32px;
    border: 1px solid #2d2d44;
}
.header h1 { font-size: 28px; color: #fff; margin-bottom: 4px; }
.header .subtitle { color: #888; font-size: 14px; }
.header .meta { color: #666; font-size: 12px; margin-top: 12px; }
.stats {
    display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap;
}
.stat-card {
    background: #1a1a2e; border: 1px solid #2d2d44; border-radius: 12px;
    padding: 20px 28px; min-width: 160px;
}
.stat-card .label { font-size: 12px; color: #888; text-transform: uppercase;
    letter-spacing: 1px; margin-bottom: 4px; }
.stat-card .value { font-size: 28px; font-weight: 700; color: #00b894; }
.stat-card .value.accent { color: #e94560; }
.stat-card .value.warn { color: #fdcb6e; }
table {
    width: 100%; border-collapse: collapse; background: #1a1a2e;
    border-radius: 12px; overflow: hidden; border: 1px solid #2d2d44;
}
thead th {
    background: #16213e; color: #aaa; font-size: 11px;
    text-transform: uppercase; letter-spacing: 1px; padding: 14px 16px;
    text-align: left; border-bottom: 2px solid #2d2d44;
    position: sticky; top: 0;
}
tbody td {
    padding: 10px 16px; border-bottom: 1px solid #222238;
    font-size: 13px; max-width: 300px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
}
tbody tr:hover { background: #222238; }
tbody tr:nth-child(even) { background: #151528; }
.badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600;
}
.badge-green { background: #00b89422; color: #00b894; }
.badge-red { background: #e9456022; color: #e94560; }
.badge-yellow { background: #fdcb6e22; color: #fdcb6e; }
.badge-blue { background: #0984e322; color: #74b9ff; }
.footer {
    text-align: center; color: #444; font-size: 11px;
    margin-top: 32px; padding-top: 16px; border-top: 1px solid #222;
}
"""

# Fields that get badge styling
_BADGE_MAP = {
    "true": "badge-green", "false": "badge-red",
    "active": "badge-green", "infected": "badge-red",
    "mitigated": "badge-green", "not_mitigated": "badge-red",
    "suspicious": "badge-yellow", "malicious": "badge-red",
    "critical": "badge-red", "high": "badge-red",
    "medium": "badge-yellow", "low": "badge-blue",
    "finished": "badge-green", "running": "badge-yellow",
    "enabled": "badge-green", "disabled": "badge-red",
}


def _badge(val: str) -> str:
    v = str(val).lower().strip()
    cls = _BADGE_MAP.get(v, "")
    if cls:
        return f'<span class="badge {cls}">{val}</span>'
    return str(val)


def _cell(val) -> str:
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)[:120]
    s = str(val)
    return s[:200] if len(s) > 200 else s


def generate_html(title: str, columns: list[str], rows: list[dict],
                  stats: Optional[list[dict]] = None,
                  subtitle: str = "") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats_html = ""
    if stats:
        cards = ""
        for s in stats:
            cls = s.get("class", "")
            cards += (f'<div class="stat-card"><div class="label">{s["label"]}</div>'
                      f'<div class="value {cls}">{s["value"]}</div></div>')
        stats_html = f'<div class="stats">{cards}</div>'

    # Table
    th = "".join(f"<th>{c}</th>" for c in columns)
    tr_list = []
    for row in rows:
        tds = "".join(f"<td>{_badge(_cell(row.get(c, '')))}</td>" for c in columns)
        tr_list.append(f"<tr>{tds}</tr>")
    tbody = "\n".join(tr_list)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — S1 Command Center Report</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>{title}</h1>
  <div class="subtitle">{subtitle or 'S1 Command Center Report'}</div>
  <div class="meta">Generated {now} &bull; {len(rows)} records</div>
</div>
{stats_html}
<table><thead><tr>{th}</tr></thead><tbody>{tbody}</tbody></table>
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi &bull; Generated {now}</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
#  Backup redaction (safe-to-share copies)
# ═══════════════════════════════════════════════════════════════════════

REDACTED = "***REDACTED***"

# A key is treated as secret if its name contains any of these (case-insensitive).
# Backups embed real secrets in the settings blocks — SMTP relay passwords, AD
# bind credentials, syslog tokens, SSO client secrets / private keys, webhook
# auth headers — so a backup JSON shared on a ticket or chat is a credential
# leak. Redaction produces a sanitised COPY for sharing; the working backup
# used for restore is never modified.
_SECRET_KEY_PARTS = (
    "password", "passwd", "passphrase", "secret", "token", "apikey",
    "api_key", "privatekey", "private_key", "clientsecret", "client_secret",
    "bindpassword", "bind_password", "credential", "authorization", "bearer",
)


def _is_secret_key(key) -> bool:
    k = str(key).lower().replace("-", "").replace("_", "")
    return any(p.replace("_", "") in k for p in _SECRET_KEY_PARTS)


def _redact_obj(obj, counter):
    """Recursively return a redacted deep copy, counting masked values."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and v not in (None, "", [], {}):
                out[k] = REDACTED
                counter[0] += 1
            else:
                out[k] = _redact_obj(v, counter)
        return out
    if isinstance(obj, list):
        return [_redact_obj(i, counter) for i in obj]
    return obj


def count_backup_secrets(nodes) -> int:
    """How many secret values a backup contains (0 = safe to share as-is)."""
    counter = [0]
    _redact_obj(nodes or [], counter)
    return counter[0]


def redact_backup(nodes):
    """Return (redacted_copy, count) — a deep copy of the backup with every
    secret-looking value masked. Input is not mutated."""
    counter = [0]
    redacted = _redact_obj(nodes or [], counter)
    return redacted, counter[0]


# ═══════════════════════════════════════════════════════════════════════
#  Migration Manifest (for the PSO ticket-closing workflow)
# ═══════════════════════════════════════════════════════════════════════

def build_migration_manifest(meta: dict, results: list[dict]) -> dict:
    """Turn a Migration Validation result set (meta + results, the structure
    produced by ValidationPage._run_validation) into a structured, portable
    manifest of what was migrated and how it verified.

    Pure function — no GUI/network. Safe to unit-test."""
    meta = meta or {}
    results = results or []

    n = len(results)
    missing = sum(1 for r in results if not r.get("matched"))
    with_diffs = sum(1 for r in results
                     if r.get("matched") and r.get("diffs", 0) > 0)
    identical = n - missing - with_diffs
    total_diffs = sum(r.get("diffs", 0) for r in results if r.get("matched"))

    if n == 0:
        status = "incomplete"
    elif missing == 0 and with_diffs == 0:
        status = "verified"
    else:
        status = "differences"

    nodes = []
    for r in results:
        if not r.get("matched"):
            outcome = "missing"
            diffs = []
        elif r.get("diffs", 0) == 0:
            outcome = "identical"
            diffs = []
        else:
            outcome = "differences"
            diffs = [
                {
                    "element": x.get("cat"),
                    "src": x.get("src"),
                    "dst": x.get("dst"),
                    "missing": x.get("missing", []),
                    "extra": x.get("extra", []),
                }
                for x in r.get("rows", []) if x.get("status") == "diff"
            ]
        nodes.append({
            "type": r.get("type"),
            "path": r.get("path"),
            "result": outcome,
            "differences": diffs,
        })

    return {
        "tool": "S1 Command Center",
        "kind": "migration-manifest",
        "version": 1,
        "generatedAt": meta.get("when"),
        "source": meta.get("src_url"),
        "destination": meta.get("dst_url"),
        "levels": meta.get("levels", []),
        "scope": {
            "source": meta.get("src_filters", {}),
            "destination": meta.get("dst_filters", {}),
        },
        "summary": {
            "nodesCompared": n,
            "identical": identical,
            "withDifferences": with_diffs,
            "missingOnDestination": missing,
            "totalDifferences": total_diffs,
            "status": status,
        },
        "nodes": nodes,
    }


def manifest_to_pso_comment(manifest: dict) -> str:
    """Render a migration manifest as a Markdown comment ready for the PSO
    Jira ticket-closing workflow ('done with PSO-XXX'). Mirrors the agreed
    Migration Summary template so the comment can be posted as-is."""
    m = manifest or {}
    s = m.get("summary", {})
    when = (m.get("generatedAt") or "")[:10] or "—"
    status = s.get("status")

    if status == "verified":
        headline = "Migration completed successfully ✅"
        status_line = "All settings transferred and verified."
    elif status == "differences":
        headline = "Migration completed — review needed ⚠️"
        status_line = (
            f"{s.get('totalDifferences', 0)} difference(s) across "
            f"{s.get('withDifferences', 0)} node(s); "
            f"{s.get('missingOnDestination', 0)} scope(s) missing on "
            f"destination. See details below.")
    else:
        headline = "Migration validation incomplete"
        status_line = "No nodes were compared — re-run validation."

    src_scope = (m.get("scope", {}).get("source") or {})
    scope_txt = (f"account: {src_scope.get('account') or 'all'} · "
                 f"site: {src_scope.get('site') or 'all'}")
    levels = ", ".join(m.get("levels", [])) or "—"

    lines = [
        headline,
        "",
        "**Migration Summary**",
        f"- **Source:** {m.get('source') or '?'}",
        f"- **Destination:** {m.get('destination') or '?'}",
        f"- **Completed:** {when}",
        f"- **Scope:** levels [{levels}] · {scope_txt}",
        f"- **Validation:** {s.get('nodesCompared', 0)} node(s) compared — "
        f"{s.get('identical', 0)} identical, "
        f"{s.get('withDifferences', 0)} with differences, "
        f"{s.get('missingOnDestination', 0)} missing on destination",
        f"- **Status:** {status_line}",
    ]

    # Per-node difference detail (only when there is something to flag).
    flagged = [nd for nd in m.get("nodes", [])
               if nd.get("result") in ("differences", "missing")]
    if flagged:
        lines += ["", "**Items needing attention**"]
        for nd in flagged:
            if nd.get("result") == "missing":
                lines.append(
                    f"- `{nd.get('path')}` — scope missing on destination "
                    f"(renamed or not created)")
                continue
            for d in nd.get("differences", []):
                detail = []
                if d.get("missing"):
                    miss = d["missing"]
                    shown = ", ".join(miss[:8])
                    if len(miss) > 8:
                        shown += f" (+{len(miss) - 8} more)"
                    detail.append(f"missing: {shown}")
                if d.get("extra"):
                    detail.append(f"{len(d['extra'])} extra on dest")
                tail = f" ({'; '.join(detail)})" if detail else ""
                lines.append(
                    f"- `{nd.get('path')}` / {d.get('element')}: "
                    f"{d.get('src')} → {d.get('dst')}{tail}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  Excel Report (via openpyxl)
# ═══════════════════════════════════════════════════════════════════════

def generate_excel(path: str, title: str, columns: list[str],
                   rows: list[dict]):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    # Colors
    header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e",
                              fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10, color="333333")
    alt_fill = PatternFill(start_color="F5F6FA", end_color="F5F6FA",
                           fill_type="solid")
    border = Border(
        bottom=Side(style="thin", color="E0E0E0"))

    # Title row
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1, end_column=max(len(columns), 1))
    cell = ws.cell(row=1, column=1, value=f"{title} — S1 Command Center Report")
    cell.font = Font(name="Segoe UI", size=14, bold=True, color="1a1a2e")
    cell.alignment = Alignment(horizontal="left")

    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2, end_column=max(len(columns), 1))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cell2 = ws.cell(row=2, column=1,
                    value=f"Generated {now}  •  {len(rows)} records")
    cell2.font = Font(name="Segoe UI", size=9, color="888888")

    # Header row
    for j, col in enumerate(columns, 1):
        c = ws.cell(row=4, column=j, value=col)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="left")

    # Data rows
    for i, row in enumerate(rows):
        r = i + 5
        fill = alt_fill if i % 2 == 0 else None
        for j, col in enumerate(columns, 1):
            val = row.get(col, "")
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            c = ws.cell(row=r, column=j, value=val)
            c.font = data_font
            c.border = border
            if fill:
                c.fill = fill

    # Auto-width
    for j, col in enumerate(columns, 1):
        max_len = len(col)
        for i, row in enumerate(rows[:200]):
            val = str(row.get(col, ""))
            max_len = max(max_len, min(len(val), 50))
        ws.column_dimensions[ws.cell(row=4, column=j).column_letter].width = \
            max_len + 4

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{ws.cell(row=4, column=len(columns)).column_letter}4"
    wb.save(path)


# ═══════════════════════════════════════════════════════════════════════
#  Unified export dialog
# ═══════════════════════════════════════════════════════════════════════

def export_report(title: str, columns: list[str], rows: list[dict],
                  stats: Optional[list[dict]] = None,
                  subtitle: str = ""):
    """Show save dialog and export as HTML or Excel based on user choice."""
    if not rows:
        messagebox.showwarning("No Data", "Nothing to export — load data first.")
        return

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    safe_title = title.lower().replace(" ", "-").replace("&", "and")
    path = filedialog.asksaveasfilename(
        title=f"Export {title}",
        initialfile=f"s1-{safe_title}-{ts}",
        defaultextension=".html",
        filetypes=[
            ("HTML Report", "*.html"),
            ("Excel Workbook", "*.xlsx"),
            ("JSON Data", "*.json"),
        ],
    )
    if not path:
        return

    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".xlsx":
            generate_excel(path, title, columns, rows)
        elif ext == ".json":
            with open(path, "w") as f:
                json.dump(rows, f, indent=2, default=str)
        else:
            html = generate_html(title, columns, rows, stats=stats,
                                 subtitle=subtitle)
            with open(path, "w") as f:
                f.write(html)

        cli_log(f"Exported {len(rows)} records → {os.path.basename(path)}",
                "success")
        cli_log(f"File saved to: {path}", "info")
    except Exception as e:
        cli_log(f"Export error: {e}", "error")
        messagebox.showerror("Export Error", str(e))
