import math
import re
from collections import Counter
from datetime import datetime, timezone

from config import APP_VERSION
from export_utils import (GAP_ELEMENT_TITLES, GAP_INFO_STATUSES,
                          GAP_MISSING_STATUSES, GAP_RESTORED_STATUSES,
                          _REPORT_JS, _esc, build_gap_report)

REPORT_KIND = "s1-migration-report"
REPORT_VERSION = 1
GAP_ROW_CAP = 1000
SUCCESS_ROW_CAP = 5000
LOG_LINE_CAP = 50000
CLEAN_NODE_CAP = 400
SUPPORT_LINE_CAP = 200

NODE_OUTCOMES = (
    ("restored", "Restored", "green", "green"),
    ("partial", "With gaps", "yellow", "yellow"),
    ("failed", "Failed", "red", "red"),
    ("interrupted", "Interrupted", "red", "rose"),
    ("skipped", "Skipped", "blue", "blue"),
    ("not run", "Not run", "yellow", "gray"),
)
OUTCOME_LABELS = {k: label for k, label, _, _ in NODE_OUTCOMES}
OUTCOME_BADGES = {k: badge for k, _, badge, _ in NODE_OUTCOMES}
OUTCOME_SEGMENTS = {k: seg for k, _, _, seg in NODE_OUTCOMES}
_OUTCOME_RANK = {"failed": 0, "interrupted": 0, "not run": 1, "partial": 2,
                 "skipped": 3, "restored": 4}

ITEM_STATUSES = (
    ("created", "Created", "green",
     "New on the destination — this migration made it."),
    ("exists", "Already there", "blue",
     "An item with the same identity was already on the destination, so "
     "nothing had to change."),
    ("failed", "Failed", "red",
     "The destination rejected it. The Failures tab explains each error and "
     "how to fix it."),
    ("skipped", "Skipped", "yellow",
     "Deliberately not restored — a dead source scope, an element skipped "
     "during the run, or an item that cannot exist at this level. The reason "
     "column says which."),
    ("manual", "Manual", "yellow",
     "There is no public API for it, so it has to be recreated by hand on "
     "the destination."),
    ("not attempted", "Not in backup", "red",
     "Ticked for restore, but the backup never captured it — take a fresh "
     "backup with the element ticked."),
    ("inherited", "Inherited", "blue",
     "Belongs to a parent scope and is restored there. Not a gap."),
    ("empty", "Empty", "blue",
     "The backup legitimately holds none of these for this scope. Not a gap."),
)
STATUS_LABELS = {k: label for k, label, _, _ in ITEM_STATUSES}
STATUS_BADGES = {k: badge for k, _, badge, _ in ITEM_STATUSES}

_SEVERITY_RANK = {"critical": 0, "error": 1, "warning": 2, "warn": 2,
                  "info": 3}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
_CODE_RE = re.compile(r"→\s*(\d{3})")
_PRESENCE_SUFFIX = " (present?)"


def _dicts(value):
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)]


def _int(value, default=0):
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_when(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), timezone.utc)
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def fmt_when(value, seconds=False):
    parsed = parse_when(value)
    if parsed is None:
        return "—"
    return parsed.astimezone().strftime(
        "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def fmt_duration(seconds):
    if seconds is None:
        return "—"
    total = int(round(max(0.0, float(seconds))))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def fmt_bytes(size):
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value):,} B" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024.0
    return f"{value:,.1f} GB"


def span_seconds(start, end):
    first, last = parse_when(start), parse_when(end)
    if first is None or last is None:
        return None
    return max(0.0, (last - first).total_seconds())


def host_of(url):
    return str(url or "").split("//", 1)[-1].split("/", 1)[0]


def pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else None


def _strip_presence(label):
    label = str(label or "")
    if label.endswith(_PRESENCE_SUFFIX):
        return label[:-len(_PRESENCE_SUFFIX)]
    return label


def element_title(key, cat_label=None):
    key = str(key or "other")
    if key in GAP_ELEMENT_TITLES:
        return GAP_ELEMENT_TITLES[key]
    if cat_label is not None:
        try:
            label = _strip_presence(cat_label(key))
        except Exception:
            label = ""
        if label and label != key:
            return label
    text = key.replace("_", " ").replace("-", " ").strip()
    return (text[:1].upper() + text[1:]) if text else "Other"


def console_version(info):
    if not isinstance(info, dict):
        return ""
    bits = [f"{key} {info[key]}" for key in ("release", "build", "patch")
            if info.get(key) not in (None, "")]
    return ", ".join(bits) or str(info.get("version") or "")


def _person(user):
    if not isinstance(user, dict):
        return ""
    name = str(user.get("fullName") or user.get("name") or "")
    email = str(user.get("email") or "")
    if name and email:
        return f"{name} <{email}>"
    return name or email


def _path_parts(path, ntype):
    path = str(path or "")
    if ntype == "global" or path in ("", "/"):
        return "", "", ""
    account, _, rest = path.partition("/")
    if ntype == "account":
        return account, "", ""
    if ntype == "site":
        return account, rest, ""
    site, _, group = rest.rpartition("/")
    return account, site, group


def _merge_runs(runs):
    covered = set()
    nodes, ledger = [], []
    for run in reversed(runs):
        run_nodes = _dicts(run.get("nodes"))
        run_ledger = _dicts(run.get("ledger"))
        touched = ({str(n.get("path") or "") for n in run_nodes}
                   | {str(r.get("node") or "") for r in run_ledger})
        nodes = [n for n in run_nodes
                 if str(n.get("path") or "") not in covered] + nodes
        ledger = [r for r in run_ledger
                  if str(r.get("node") or "") not in covered] + ledger
        covered |= touched
    return nodes, ledger


def _node_outcome(state, detail, missing, failed_items):
    if state == "done":
        return "partial" if (missing or failed_items) else "restored"
    if state == "error":
        return "failed"
    if state == "running":
        return "interrupted"
    if state == "skipped":
        return ("not run" if str(detail).lower().startswith("cancel")
                else "skipped")
    return "not run"


def _node_rows(progress, nodes, ledger):
    reports = {str(n.get("path") or ""): n for n in nodes}
    tallies, scope_rows = {}, {}
    for row in ledger:
        node = str(row.get("node") or "")
        tallies.setdefault(node, Counter())[str(row.get("status") or "")] += 1
        if row.get("element") == "(node)":
            scope_rows[node] = row
    base = _dicts(progress)
    if not base:
        base = [{"path": n.get("path"), "type": n.get("type"),
                 "status": n.get("status") or "done",
                 "detail": n.get("summary") or ""} for n in nodes]
        known = {str(b.get("path") or "") for b in base}
        for path, row in scope_rows.items():
            if path not in known:
                base.append({
                    "path": path, "type": row.get("scope"),
                    "status": ("error" if row.get("status") == "failed"
                               else "skipped"),
                    "detail": row.get("reason") or ""})
    rows = []
    for item in base:
        path = str(item.get("path") or "")
        rep = reports.get(path) or {}
        tally = tallies.get(path) or Counter()
        ntype = str(item.get("type") or rep.get("type") or "")
        failed_items = _dicts(rep.get("failed_items"))
        missing = sum(tally[s] for s in GAP_MISSING_STATUSES)
        state = str(item.get("status") or rep.get("status") or "pending")
        detail = str(item.get("detail") or rep.get("summary") or "")
        account, site, group = _path_parts(path, ntype)
        num = item.get("num")
        if num is None and isinstance(rep.get("index"), int):
            num = rep["index"] + 1
        seconds = rep.get("seconds")
        rows.append({
            "path": path, "type": ntype, "num": num,
            "account": account, "site": site,
            "name": group or site or account or "Global",
            "state": state,
            "outcome": _node_outcome(state, detail, missing, failed_items),
            "detail": detail,
            "created": tally["created"], "exists": tally["exists"],
            "failed": tally["failed"], "missing": missing,
            "info": sum(tally[s] for s in GAP_INFO_STATUSES),
            "seconds": (float(seconds) if isinstance(seconds, (int, float))
                        and not isinstance(seconds, bool) else None),
            "started_at": rep.get("started_at"),
            "dest_id": str(rep.get("dest_id") or ""),
            "failed_items": len(failed_items),
            "reason": str((scope_rows.get(path) or {}).get("reason") or ""),
        })
    return rows


def _node_stats(rows):
    counts = Counter(r["outcome"] for r in rows)
    by_type = {}
    for row in rows:
        tally = by_type.setdefault(row["type"] or "?", Counter())
        tally["total"] += 1
        tally[row["outcome"]] += 1
    return {"total": len(rows),
            "counts": {k: counts.get(k, 0) for k, _, _, _ in NODE_OUTCOMES},
            "by_type": {k: dict(v) for k, v in by_type.items()}}


def _site_cards(rows):
    cards, order = {}, []
    for row in rows:
        if row["type"] == "global":
            key, title, sub, kind = ("", ""), "Global", "console-wide", "global"
        elif row["type"] == "account":
            key = (row["account"], "")
            title, sub, kind = row["account"] or row["path"], "account", "account"
        else:
            key = (row["account"], row["site"])
            title, sub, kind = row["site"] or row["path"], row["account"], "site"
        card = cards.get(key)
        if card is None:
            card = cards[key] = {
                "title": title, "sub": sub, "kind": kind, "node": None,
                "groups": [], "tally": Counter(), "created": 0,
                "missing": 0, "seconds": 0.0}
            order.append(key)
        if row["type"] == "group":
            card["groups"].append(row)
        else:
            card["node"] = row
        card["tally"][row["outcome"]] += 1
        card["created"] += row["created"]
        card["missing"] += row["missing"]
        card["seconds"] += row["seconds"] or 0.0
    out = []
    for key in order:
        card = cards[key]
        tally = card.pop("tally")
        card["counts"] = {k: tally.get(k, 0) for k, _, _, _ in NODE_OUTCOMES}
        card["total"] = sum(tally.values())
        card["outcome"] = (min(tally, key=lambda k: _OUTCOME_RANK.get(k, 9))
                           if tally else "not run")
        out.append(card)
    return out


def _run_summaries(runs):
    out = []
    for n, run in enumerate(runs, 1):
        meta = run.get("meta") or {}
        if meta.get("run_failed"):
            outcome = "aborted"
        elif meta.get("cancelled"):
            outcome = "stopped"
        elif meta.get("end_time"):
            outcome = "completed"
        else:
            outcome = "unfinished"
        out.append({
            "n": n,
            "start": str(meta.get("start_time") or ""),
            "end": str(meta.get("end_time") or ""),
            "seconds": span_seconds(meta.get("start_time"),
                                    meta.get("end_time")),
            "outcome": outcome,
            "nodes": len(_dicts(run.get("nodes"))),
            "items": len(_dicts(run.get("ledger"))),
            "unattended": bool(meta.get("unattended")),
            "resumed": bool(meta.get("resumed")) or n > 1,
            "error": str(meta.get("error") or ""),
            "snapshot_path": str(meta.get("snapshot_path") or ""),
            "snapshot_error": str(meta.get("snapshot_error") or ""),
            "snapshot_requested": bool(meta.get("snapshot_requested")),
        })
    return out


def _snapshot_state(runs):
    for run in runs:
        if run["snapshot_path"]:
            return {"state": "saved", "path": run["snapshot_path"]}
    for run in runs:
        if run["snapshot_error"]:
            return {"state": "failed", "error": run["snapshot_error"]}
    if any(run["snapshot_requested"] for run in runs):
        return {"state": "empty"}
    return {"state": "off"}


def _explain(explain, element, error, code):
    found = {}
    if explain is not None:
        try:
            found = explain(element, error, code) or {}
        except Exception:
            found = {}
    what = str(found.get("what") or "")
    if element == "(node)" and (not what or what.startswith("Unrecognised")):
        return {
            "what": "Scope could not be created on the destination",
            "why": "The destination rejected or could not find this account, "
                   "site or group, so nothing below it was restored.",
            "fix": "Read the console's reason in the item list — usually a "
                   "missing permission such as Accounts.create, a name clash "
                   "or a licence limit. Fix it, then Resume: finished scopes "
                   "are skipped.",
            "severity": "error"}
    return {"what": what or f"{element_title(element)} could not be restored",
            "why": str(found.get("why") or ""),
            "fix": str(found.get("fix") or ""),
            "severity": str(found.get("severity") or "error")}


def _failures(nodes, ledger, explain):
    items, seen = [], set()
    for row in ledger:
        if str(row.get("status") or "") != "failed":
            continue
        item = {"path": str(row.get("node") or ""),
                "element": str(row.get("element") or "?"),
                "name": str(row.get("item") or ""),
                "error": str(row.get("reason") or "")}
        seen.add((item["path"], item["element"], item["name"]))
        items.append(item)
    for node in nodes:
        path = str(node.get("path") or "")
        for failed in _dicts(node.get("failed_items")):
            item = {"path": path,
                    "element": str(failed.get("element") or "?"),
                    "name": str(failed.get("name") or ""),
                    "error": str(failed.get("error") or "")}
            key = (item["path"], item["element"], item["name"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    groups = {}
    for item in items:
        match = _CODE_RE.search(item["error"])
        found = _explain(explain, item["element"], item["error"],
                         int(match.group(1)) if match else 0)
        group = groups.get(found["what"])
        if group is None:
            group = groups[found["what"]] = dict(found, items=[],
                                                 tally=Counter())
        group["items"].append(item)
        group["tally"][item["element"]] += 1
    out = []
    for group in groups.values():
        tally = group.pop("tally")
        group["count"] = len(group["items"])
        group["nodes"] = len({i["path"] for i in group["items"]})
        group["elements"] = [{"key": k, "title": element_title(k), "count": v}
                             for k, v in tally.most_common()]
        out.append(group)
    out.sort(key=lambda g: (_SEVERITY_RANK.get(g["severity"], 9),
                            -g["count"], g["what"]))
    return {"total": len(items), "groups": out,
            "nodes": len({i["path"] for i in items}),
            "elements": len({i["element"] for i in items}),
            "scopes": sum(1 for i in items if i["element"] == "(node)")}


def _successes(outcomes, node_rows):
    tiles, rows = [], []
    for element in outcomes["elements"]:
        counts = element["counts"]
        if element["key"] != "(node)" and element["restored"]:
            tiles.append({"key": element["key"], "title": element["title"],
                          "created": counts.get("created", 0),
                          "exists": counts.get("exists", 0),
                          "restored": element["restored"],
                          "total": element["total"],
                          "missing": element["missing"]})
        for row in element["rows"]:
            if str(row.get("status")) in GAP_RESTORED_STATUSES:
                rows.append({"node": str(row.get("node") or ""),
                             "scope": str(row.get("scope") or ""),
                             "element": element["title"],
                             "item": str(row.get("item") or ""),
                             "kind": str(row.get("kind") or ""),
                             "status": str(row.get("status"))})
    tiles.sort(key=lambda t: (-t["created"], -t["restored"],
                              t["title"].lower()))
    clean = [r["path"] for r in node_rows if r["outcome"] == "restored"]
    return {"tiles": tiles, "rows": rows[:SUCCESS_ROW_CAP],
            "row_total": len(rows), "clean_nodes": clean}


def _gaps(outcomes):
    elements = []
    for element in outcomes["elements"]:
        missing_rows = [r for r in element["rows"]
                        if str(r.get("status")) in GAP_MISSING_STATUSES]
        info_rows = [r for r in element["rows"]
                     if str(r.get("status")) in GAP_INFO_STATUSES]
        elements.append({
            "key": element["key"], "title": element["title"],
            "counts": element["counts"], "restored": element["restored"],
            "missing": element["missing"], "info": element["info"],
            "total": element["total"], "missing_rows": missing_rows,
            "info_rows": info_rows[:GAP_ROW_CAP],
            "info_total": len(info_rows)})
    return {"totals": outcomes["totals"], "elements": elements}


def _classify_read(value):
    if isinstance(value, bool):
        return "ok", 0
    if isinstance(value, (int, float)):
        return "ok", int(value)
    text = str(value or "").strip()
    if text.isdigit():
        return "ok", int(text)
    low = text.lower()
    if low.startswith("n/a"):
        return "denied", 0
    if low == "no api":
        return "unsupported", 0
    if low.startswith("err"):
        return "error", 0
    return "ok", 0


def _backup_reads(nodes, cat_label):
    elements, order, recorded = {}, [], False
    for node in nodes:
        results = node.get("backupResults")
        if not isinstance(results, dict):
            continue
        recorded = True
        path = str(node.get("path") or "")
        for label, value in results.items():
            entry = elements.get(label)
            if entry is None:
                entry = elements[label] = {
                    "key": str(label), "title": element_title(label, cat_label),
                    "ok": 0, "items": 0, "denied": [], "errors": [],
                    "unsupported": 0}
                order.append(label)
            kind, count = _classify_read(value)
            if kind == "ok":
                entry["ok"] += 1
                entry["items"] += count
            elif kind == "unsupported":
                entry["unsupported"] += 1
            else:
                entry["denied" if kind == "denied" else "errors"].append(
                    {"path": path, "detail": str(value)})
    rows = [elements[k] for k in order]
    return {"recorded": recorded, "elements": rows,
            "errors": sum(len(e["errors"]) for e in rows),
            "denied": sum(len(e["denied"]) for e in rows),
            "unsupported": [e["title"] for e in rows
                            if e["unsupported"] and not e["ok"]]}


def _backup_inventory(nodes, summarize, cat_label):
    cats, per_node = {}, {}
    if summarize is None:
        return [], per_node
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict) or not data:
            continue
        try:
            rows = summarize(data) or []
        except Exception:
            continue
        total = 0
        for row in rows:
            try:
                cat, count = row[0], _int(row[1])
            except (IndexError, TypeError):
                continue
            if count <= 0:
                continue
            entry = cats.get(cat)
            if entry is None:
                raw = str(cat_label(cat)) if cat_label is not None else str(cat)
                presence = raw.endswith(_PRESENCE_SUFFIX)
                entry = cats[cat] = {
                    "key": str(cat), "presence": presence,
                    "label": element_title(cat, cat_label),
                    "items": 0, "nodes": 0}
            entry["items"] += count
            entry["nodes"] += 1
            if not entry["presence"]:
                total += count
        per_node[str(node.get("path") or "")] = total
    ordered = sorted(cats.values(),
                     key=lambda e: (e["presence"], -e["items"],
                                    e["label"].lower()))
    return ordered, per_node


def _backup_tree(nodes, outcomes, per_node):
    globals_, accounts = [], {}

    def entry(node, name):
        path = str(node.get("path") or "")
        return {"name": name, "path": path,
                "type": str(node.get("type") or ""),
                "outcome": outcomes.get(path, ""),
                "items": per_node.get(path, 0)}

    for node in nodes:
        ntype = str(node.get("type") or "")
        if ntype == "global":
            globals_.append(entry(node, "Global"))
            continue
        account, site, group = _path_parts(node.get("path"), ntype)
        acct = accounts.setdefault(account, {"name": account, "node": None,
                                             "sites": {}})
        if ntype == "account":
            acct["node"] = entry(node, account)
        elif ntype in ("site", "group"):
            site_entry = acct["sites"].setdefault(
                site, {"name": site, "node": None, "groups": []})
            if ntype == "site":
                site_entry["node"] = entry(node, site)
            else:
                site_entry["groups"].append(entry(node, group))
    return {"global": globals_,
            "accounts": [{"name": a["name"], "node": a["node"],
                          "sites": list(a["sites"].values())}
                         for a in accounts.values()]}


def _backup_section(nodes, file_info, integrity, secret_count, renames,
                    summarize, cat_label, node_rows):
    meta = next((n["backupMetadata"] for n in nodes
                 if isinstance(n.get("backupMetadata"), dict)
                 and n["backupMetadata"]), {})
    run = meta.get("run") if isinstance(meta.get("run"), dict) else {}
    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    inventory, per_node = _backup_inventory(nodes, summarize, cat_label)
    outcomes = {row["path"]: row["outcome"] for row in node_rows}
    filters = scope.get("filters")
    levels = scope.get("levels")
    seconds = run.get("seconds")
    return {
        "file": dict(file_info or {}),
        "url": str(meta.get("url") or ""),
        "format": str(meta.get("backupVersion") or ""),
        "snapshot": bool(meta.get("snapshot")),
        "taken": str(run.get("started") or meta.get("start") or ""),
        "finished": str(run.get("finished") or ""),
        "seconds": (float(seconds) if isinstance(seconds, (int, float))
                    and not isinstance(seconds, bool) else None),
        "by": _person(run.get("runBy")) or _person(meta.get("runByUser")),
        "tool_version": str(run.get("toolVersion") or ""),
        "console_version": console_version(meta.get("systemInformation")),
        "filters": (filters if isinstance(filters, dict)
                    else dict(run.get("filters") or {})),
        "levels": (levels if isinstance(levels, dict)
                   else dict(run.get("levels") or {})),
        "elements": [element_title(e, cat_label)
                     for e in (run.get("elements") or [])],
        "cancelled": bool(run.get("cancelled")),
        "nodes_planned": run.get("nodesPlanned"),
        "nodes_saved": run.get("nodesSaved") if run else len(nodes),
        "failed_nodes": _dicts(run.get("failedNodes")),
        "has_run_record": bool(run),
        "node_count": len(nodes),
        "types": dict(Counter(str(n.get("type") or "?") for n in nodes)),
        "inventory": inventory,
        "item_total": sum(e["items"] for e in inventory if not e["presence"]),
        "reads": _backup_reads(nodes, cat_label),
        "integrity": integrity if isinstance(integrity, dict) else None,
        "secret_count": _int(secret_count),
        "renames": _dicts(renames),
        "tree": _backup_tree(nodes, outcomes, per_node),
    }


def _preflight_section(preflight):
    if not isinstance(preflight, dict):
        return None
    checks = [{"name": str(c.get("name") or ""),
               "status": str(c.get("status") or "info"),
               "detail": str(c.get("detail") or "")}
              for c in _dicts(preflight.get("checks"))]
    return {"at": str(preflight.get("at") or ""),
            "verdict": str(preflight.get("verdict") or ""),
            "dest": str(preflight.get("dest") or ""), "checks": checks,
            "counts": dict(Counter(c["status"] for c in checks))}


def _preview_section(preview, totals):
    if not isinstance(preview, dict):
        return None
    return {"at": str(preview.get("at") or ""),
            "dest": str(preview.get("dest") or ""),
            "create": _int(preview.get("create")),
            "exists": _int(preview.get("exists")),
            "missing": _int(preview.get("missing")),
            "nodes": _int(preview.get("nodes")),
            "per_element": [{"label": _strip_presence(e.get("label")),
                             "create": _int(e.get("create")),
                             "exists": _int(e.get("exists"))}
                            for e in _dicts(preview.get("per_element"))],
            "actual_created": _int(totals.get("created")),
            "actual_exists": _int(totals.get("exists"))}


def _validation_section(validation, meta, cat_label):
    if not isinstance(validation, dict):
        return None
    results = _dicts(validation.get("results"))
    if not results:
        return None
    vmeta = validation.get("meta") if isinstance(validation.get("meta"),
                                                 dict) else {}
    matched = [r for r in results if r.get("matched")]
    differing = [r for r in matched if _int(r.get("diffs")) > 0]
    diffs = []
    for result in matched:
        for row in _dicts(result.get("rows")):
            if row.get("status") != "diff":
                continue
            diffs.append({
                "path": str(result.get("path") or ""),
                "type": str(result.get("type") or ""),
                "label": element_title(row.get("cat"), cat_label),
                "src": row.get("src"), "dst": row.get("dst"),
                "missing": [str(x) for x in (row.get("missing") or [])][:50],
                "extra": [str(x) for x in (row.get("extra") or [])][:50],
                "what": str(row.get("what") or ""),
                "why": str(row.get("why") or ""),
                "fix": str(row.get("fix") or "")})
    when = vmeta.get("when") or ""
    started, checked = parse_when(meta.get("start_time")), parse_when(when)
    return {"when": str(when), "src_url": str(vmeta.get("src_url") or ""),
            "dst_url": str(vmeta.get("dst_url") or ""),
            "nodes": len(results),
            "identical": len(matched) - len(differing),
            "differing": len(differing),
            "missing_nodes": [{"path": str(r.get("path") or ""),
                               "type": str(r.get("type") or "")}
                              for r in results if not r.get("matched")],
            "diff_total": sum(_int(r.get("diffs")) for r in matched),
            "diffs": diffs,
            "stale": bool(started and checked and checked < started),
            "cancelled": bool(vmeta.get("cancelled"))}


def _kpis(totals, node_stats, runs, failures, meta):
    counts = node_stats["counts"]
    seconds = [r["seconds"] for r in runs if r["seconds"] is not None]
    items = _int(totals.get("items"))
    restored = _int(totals.get("restored"))
    return {
        "items": items, "restored": restored,
        "missing": _int(totals.get("missing")),
        "created": _int(totals.get("created")),
        "exists": _int(totals.get("exists")),
        "failed": _int(totals.get("failed")),
        "skipped": _int(totals.get("skipped")),
        "manual": _int(totals.get("manual")),
        "not_attempted": _int(totals.get("not attempted")),
        "info": _int(totals.get("info")),
        "success_rate": pct(restored, items),
        "nodes_total": node_stats["total"],
        "nodes_restored": counts["restored"],
        "nodes_partial": counts["partial"],
        "nodes_failed": counts["failed"] + counts["interrupted"],
        "nodes_skipped": counts["skipped"],
        "nodes_not_run": counts["not run"],
        "failures": failures["total"],
        "active_seconds": sum(seconds) if seconds else None,
        "runs": len(runs),
        "elements": len(meta.get("elements") or []),
    }


def _verdict(meta, k):
    if meta.get("run_failed"):
        return {"key": "failed", "icon": "⛔", "label": "Restore aborted",
                "detail": f"The run stopped on an error: "
                          f"{meta.get('error') or 'unknown error'}. Fix it "
                          f"and Resume — scopes that finished are not redone."}
    if k["nodes_not_run"] or meta.get("cancelled"):
        n = k["nodes_not_run"]
        return {"key": "stopped", "icon": "⏸",
                "label": "Restore stopped before the end",
                "detail": (f"{n:,} scope(s) were never processed. Resume "
                           f"finishes them without redoing the rest."
                           if n else "The run was stopped before it "
                                     "finished. Resume to complete it.")}
    if k["missing"] or k["nodes_failed"]:
        bits = []
        if k["missing"]:
            bits.append(f"{k['missing']:,} of {k['items']:,} item(s) are not "
                        f"on the destination")
        if k["nodes_failed"]:
            bits.append(f"{k['nodes_failed']:,} scope(s) failed")
        return {"key": "warnings", "icon": "⚠",
                "label": "Migration finished with gaps",
                "detail": " and ".join(bits) + ". The Failures, Gaps and "
                          "Restore tabs show every one, with the reason."}
    if not k["items"]:
        return {"key": "success", "icon": "✓", "label": "Restore finished",
                "detail": "No items needed migrating in this scope."}
    return {"key": "success", "icon": "✓",
            "label": "Migration completed successfully",
            "detail": f"All {k['items']:,} item(s) in scope are on the "
                      f"destination ({k['created']:,} created, "
                      f"{k['exists']:,} already there)."}


def _route(meta, backup):
    source = backup.get("url") or meta.get("source_url") or ""
    dest = meta.get("dest_url") or ""
    return {
        "source": {"url": str(source), "host": host_of(source),
                   "version": backup.get("console_version") or ""},
        "backup": {"name": str((backup.get("file") or {}).get("name") or ""),
                   "taken": backup.get("taken") or "",
                   "nodes": backup.get("node_count", 0)},
        "destination": {"url": str(dest), "host": host_of(dest),
                        "name": str(meta.get("dest_console") or ""),
                        "customer": str(meta.get("customer") or "")},
    }


def _log_level(line):
    low = line.lower()
    if line.startswith("═══"):
        return "head"
    if ("✗" in line or "❌" in line or "⛔" in line or "error" in low
            or "failed" in low):
        return "error"
    if "⚠" in line or "warning" in low or "⏭" in line:
        return "warn"
    if "✓" in line or "✅" in line or "📸" in line:
        return "ok"
    return "info"


def _log_lines(runs):
    out, total = [], 0
    multi = len(runs) > 1
    for n, run in enumerate(runs, 1):
        lines = [str(x) for x in (run.get("log") or [])]
        total += len(lines)
        if multi and len(out) < LOG_LINE_CAP:
            out.append({"level": "head", "text": f"═══ Run {n} ═══", "run": n})
        for line in lines:
            if len(out) >= LOG_LINE_CAP:
                break
            out.append({"level": _log_level(line), "text": line, "run": n})
    return out, total


def _timeline(report, now):
    events = []

    def add(when, icon, title, detail="", tone="info"):
        moment = parse_when(when)
        if moment is not None:
            events.append({"at": moment.isoformat(), "icon": icon,
                           "title": title, "detail": detail, "tone": tone,
                           "_t": moment})

    backup = report["backup"]
    add(backup["taken"], "📦", "Backup started",
        f"Source {host_of(backup['url'])}" if backup["url"] else "")
    if backup["finished"]:
        saved = backup["nodes_saved"]
        detail = f"{_int(saved):,} scope(s) saved" if saved is not None else ""
        if backup["seconds"] is not None:
            detail += f" in {fmt_duration(backup['seconds'])}"
        add(backup["finished"], "💾",
            "Backup stopped" if backup["cancelled"] else "Backup finished",
            detail, "warn" if backup["cancelled"] else "good")
    for rename in backup["renames"]:
        add(rename.get("at"), "✏️", "Renamed in the backup",
            f"{rename.get('from')} → {rename.get('to')} "
            f"({_int(rename.get('count'))} scope(s))")
    preflight = report["readiness"]["preflight"]
    if preflight:
        add(preflight["at"], "🧪",
            f"Pre-flight: {preflight['verdict'] or 'done'}", "",
            {"pass": "good", "warn": "warn",
             "fail": "bad"}.get(preflight["verdict"], "info"))
    preview = report["readiness"]["preview"]
    if preview:
        add(preview["at"], "🔍", "Dry-run preview",
            f"{preview['create']:,} new · {preview['exists']:,} already "
            f"there (predicted)")
    runs = report["restore"]["runs"]
    for run in runs:
        label = f"Restore run {run['n']}" if len(runs) > 1 else "Restore"
        add(run["start"], "🚀", f"{label} started",
            "Resumed" if run["resumed"] and run["n"] > 1
            else ("Unattended" if run["unattended"] else ""))
        add(run["end"],
            {"completed": "🏁", "stopped": "⏸",
             "aborted": "⛔"}.get(run["outcome"], "•"),
            f"{label} {run['outcome']}",
            fmt_duration(run["seconds"]) if run["seconds"] is not None else "",
            {"completed": "good", "stopped": "warn",
             "aborted": "bad"}.get(run["outcome"], "info"))
    validation = report["validation"]
    if validation:
        clean = not validation["differing"] and not validation["missing_nodes"]
        add(validation["when"], "🔎", "Migration validation",
            f"{validation['identical']}/{validation['nodes']} scopes identical",
            "good" if clean else "warn")
    add(now.isoformat(), "📊", "This report generated")
    events.sort(key=lambda e: e["_t"])
    for event in events:
        event.pop("_t")
    return events


def _findings(report):
    k, out = report["kpis"], []
    by_type = report["restore"]["stats"]["by_type"]
    parts = []
    for ntype, word in (("global", "global"), ("account", "account"),
                        ("site", "site"), ("group", "group")):
        tally = by_type.get(ntype)
        if tally:
            done = tally.get("restored", 0) + tally.get("partial", 0)
            total = tally["total"]
            plural = "" if total == 1 or ntype == "global" else "s"
            parts.append(f"{done:,}/{total:,} {word}{plural}")
    if parts:
        complete = k["nodes_restored"] + k["nodes_partial"] == k["nodes_total"]
        out.append({"tone": "good" if complete else "warn",
                    "text": "Scopes processed: " + " · ".join(parts)})
    if k["items"]:
        out.append({"tone": "warn" if k["missing"] else "good",
                    "text": f"{k['restored']:,} of {k['items']:,} items are "
                            f"on the destination — {k['created']:,} created, "
                            f"{k['exists']:,} already there"})
    if k["missing"]:
        worst = sorted((e for e in report["gaps"]["elements"]
                        if e["missing"] and e["key"] != "(node)"),
                       key=lambda e: -e["missing"])[:3]
        where = ", ".join(f"{e['title']} ({e['missing']:,})" for e in worst)
        out.append({"tone": "bad" if k["failed"] else "warn",
                    "text": f"{k['missing']:,} item(s) did not migrate"
                            + (f" — mostly {where}" if where else "")})
    failures = report["failures"]
    if failures["total"]:
        out.append({"tone": "bad",
                    "text": f"{failures['total']:,} failure(s) in "
                            f"{len(failures['groups'])} kind(s) of error — "
                            f"each explained with a fix"})
    if failures["scopes"]:
        out.append({"tone": "bad",
                    "text": f"{failures['scopes']} scope(s) could not be "
                            f"created, so nothing below them was restored"})
    if k["nodes_not_run"]:
        out.append({"tone": "warn",
                    "text": f"{k['nodes_not_run']:,} scope(s) were never "
                            f"processed — Resume to finish"})
    runs = report["restore"]["runs"]
    if len(runs) > 1:
        out.append({"tone": "info",
                    "text": f"Done over {len(runs)} runs (stopped and "
                            f"resumed {len(runs) - 1}×)"})
    backup = report["backup"]
    if backup["node_count"]:
        source = host_of(backup["url"]) or "the source"
        taken = f" taken {fmt_when(backup['taken'])}" if backup["taken"] else ""
        out.append({"tone": "info",
                    "text": f"Backup of {source}{taken}: "
                            f"{backup['item_total']:,} items in "
                            f"{backup['node_count']:,} scopes"})
    if backup["reads"]["errors"]:
        out.append({"tone": "warn",
                    "text": f"{backup['reads']['errors']} element read(s) "
                            f"failed during the backup — those items never "
                            f"reached the file"})
    snapshot = report["restore"]["snapshot"]
    if snapshot["state"] == "saved":
        out.append({"tone": "good",
                    "text": "Rollback point saved before writing — the "
                            "change can be undone"})
    elif snapshot["state"] == "failed":
        out.append({"tone": "warn",
                    "text": "The pre-restore snapshot failed — there is no "
                            "rollback point"})
    validation = report["validation"]
    if validation:
        if validation["stale"]:
            out.append({"tone": "warn",
                        "text": "Validation results predate this restore — "
                                "re-run it"})
        elif not validation["differing"] and not validation["missing_nodes"]:
            out.append({"tone": "good",
                        "text": f"Validation: all {validation['nodes']} "
                                f"scopes match the source"})
        else:
            out.append({"tone": "warn",
                        "text": f"Validation: {validation['diff_total']:,} "
                                f"difference(s) across "
                                f"{validation['differing'] + len(validation['missing_nodes'])} "
                                f"scope(s)"})
    return out


def _recommendations(report):
    k, meta, recs = report["kpis"], report["meta"], []

    def add(priority, title, detail, tab=""):
        recs.append({"priority": priority, "title": title, "detail": detail,
                     "tab": tab})

    if meta.get("run_failed"):
        add("high", "Fix the error that stopped the restore, then Resume",
            f"The run ended with: {meta.get('error') or 'an unknown error'}. "
            f"Resume skips every scope that already finished.", "restore")
    if k["nodes_not_run"]:
        add("high", f"Resume the restore — {k['nodes_not_run']:,} scope(s) "
                    f"were never processed",
            "On the Restore screen click ↻ Resume. Scopes that finished are "
            "skipped, so nothing is written twice.", "restore")
    failures = report["failures"]
    if failures["scopes"]:
        add("high", f"{failures['scopes']} scope(s) could not be created on "
                    f"the destination",
            "Nothing below them was restored. The Failures tab shows the "
            "console's reason — usually a permission such as Accounts.create, "
            "a name clash or a licence limit. Fix it and Resume.", "failures")
    unexplained = k["nodes_failed"] - failures["scopes"]
    if unexplained > 0:
        add("high", f"{unexplained:,} scope(s) failed or were interrupted",
            "The Restore tab lists each one with its error. Fix the cause, "
            "then Resume — scopes that finished are skipped.", "restore")
    actionable = [g for g in failures["groups"]
                  if g["severity"] != "info"
                  and not all(i["element"] == "(node)" for i in g["items"])]
    for group in actionable[:3]:
        add("high" if group["severity"] in ("error", "critical") else "medium",
            f"{group['what']} — {group['count']:,} item(s)",
            group["fix"] or group["why"] or "See the Failures tab.",
            "failures")
    if len(actionable) > 3:
        rest = actionable[3:]
        add("medium", f"{len(rest)} more kind(s) of error "
                      f"({sum(g['count'] for g in rest):,} item(s))",
            "Each one is explained with the fix in the Failures tab.",
            "failures")
    harmless = [g for g in failures["groups"] if g["severity"] == "info"]
    if harmless:
        add("low", f"{sum(g['count'] for g in harmless):,} failure(s) are "
                   f"safe to ignore",
            "The console reported them, but the explanation says no action "
            "is needed (for example the item already exists).", "failures")
    gaps = report["gaps"]["elements"]

    def titles(status):
        return ", ".join(e["title"] for e in gaps if e["counts"].get(status))

    if k["manual"]:
        add("medium", f"Recreate {k['manual']:,} item(s) by hand",
            f"There is no public API for these, so they must be set up "
            f"manually on the destination: {titles('manual')}.", "gaps")
    if k["not_attempted"]:
        add("medium", f"{k['not_attempted']:,} item(s) were never in the "
                      f"backup",
            f"These elements were ticked for restore, but the backup holds "
            f"nothing for them: {titles('not attempted')}. Take a fresh "
            f"backup with them ticked, then restore just those elements.",
            "gaps")
    if k["skipped"]:
        add("low", f"Review {k['skipped']:,} skipped item(s)",
            "Skipped items were deliberately not restored. The Gaps tab "
            "gives the reason for each one.", "gaps")
    backup = report["backup"]
    integrity = backup["integrity"] or {}
    if integrity.get("errors"):
        add("high", "The backup file has integrity errors",
            "; ".join(str(e) for e in integrity["errors"][:3]), "backup")
    if backup["reads"]["errors"]:
        add("medium", f"{backup['reads']['errors']:,} element read(s) failed "
                      f"during the backup",
            "Those items never reached the backup file, so they could not "
            "be migrated. The Backup tab lists each failure — fix the cause, "
            "back up again and restore those elements.", "backup")
    if backup["failed_nodes"]:
        add("medium", f"{len(backup['failed_nodes'])} scope(s) failed to "
                      f"back up",
            "They are not in the backup file at all. The Backup tab shows "
            "the error; back them up again once it is fixed.", "backup")
    if backup["cancelled"]:
        add("medium", "The backup was stopped before it finished",
            "Scopes after the stop point are not in the file. Re-run the "
            "backup to capture everything.", "backup")
    validation = report["validation"]
    if validation is None:
        add("medium", "Validate the destination against the source",
            "Run Migration Validation (a live source ↔ destination "
            "comparison), then export this report again — it adds a "
            "Validation tab.")
    elif validation["stale"]:
        add("medium", "Re-run Migration Validation",
            "The validation results on file were produced before this "
            "restore, so they don't reflect it.", "validation")
    elif validation["differing"] or validation["missing_nodes"]:
        add("medium", f"Review {validation['diff_total']:,} validation "
                      f"difference(s)",
            "Each difference is explained with a likely cause and the fix "
            "in the Validation tab.", "validation")
    snapshot = report["restore"]["snapshot"]
    if snapshot["state"] == "saved":
        add("low", "Keep the rollback snapshot until sign-off",
            f"Saved to {snapshot['path']}. ↩ Rollback on the Restore screen "
            f"puts the destination back the way it was.", "restore")
    elif snapshot["state"] == "failed":
        add("medium", "There is no rollback point",
            f"The pre-restore snapshot failed ({snapshot['error']}). If the "
            f"change has to be undone, it must be done by hand.", "restore")
    if backup["secret_count"]:
        add("low", f"The backup holds {backup['secret_count']:,} secret "
                   f"value(s)",
            "Passwords, tokens or keys are in the backup file. Store it "
            "securely and share the redacted copy instead.", "backup")
    if integrity.get("warnings") and not integrity.get("errors"):
        add("low", f"{len(integrity['warnings'])} backup integrity "
                   f"warning(s)",
            "; ".join(str(w) for w in integrity["warnings"][:3]), "backup")
    if not report["readiness"]["preflight"]:
        add("info", "Run Pre-flight before the next restore",
            "It checks the token's permissions, licences and name clashes on "
            "the destination before anything is written.", "readiness")
    add("info", "Then move the agents",
        "Use Agent Migration to move the endpoints. If 'Scan New Agents' is "
        "on in the destination policy, migrated agents may run a full disk "
        "scan when they arrive — plan for the load or turn it off for the "
        "move.")
    if not any(r["priority"] in ("high", "medium") for r in recs):
        recs.insert(0, {"priority": "info", "title": "Nothing to fix",
                        "detail": "Everything in scope landed. Share this "
                                  "report with the customer as the record "
                                  "of the migration.", "tab": ""})
    recs.sort(key=lambda r: _PRIORITY_RANK.get(r["priority"], 9))
    return recs


def _sources(report, progress, ledger):
    backup = report["backup"]
    runs = report["restore"]["runs"]
    readiness = report["readiness"]
    return [
        {"name": "Backup file", "present": bool(backup["node_count"]),
         "detail": (f"{backup['node_count']:,} scope(s)"
                    if backup["node_count"] else "not loaded")},
        {"name": "Backup run record", "present": backup["has_run_record"],
         "detail": ("per-element read results, timing and operator"
                    if backup["has_run_record"]
                    else "not in this file (taken with an older version)")},
        {"name": "Restore runs", "present": bool(runs),
         "detail": f"{len(runs)} run(s)"},
        {"name": "Item ledger", "present": bool(ledger),
         "detail": f"{len(ledger):,} item row(s)"},
        {"name": "Scope progress", "present": bool(_dicts(progress)),
         "detail": f"{len(_dicts(progress)):,} scope row(s)"},
        {"name": "Pre-flight", "present": bool(readiness["preflight"]),
         "detail": ("included" if readiness["preflight"]
                    else "not run in this session")},
        {"name": "Dry-run preview", "present": bool(readiness["preview"]),
         "detail": ("included" if readiness["preview"]
                    else "not run in this session")},
        {"name": "Migration validation",
         "present": bool(report["validation"]),
         "detail": ("included" if report["validation"]
                    else "not run in this session")},
    ]


def _summary_text(report):
    k, verdict, route = report["kpis"], report["verdict"], report["route"]
    lines = [f"S1 migration report — {report['title']}",
             f"Result: {verdict['label']}. {verdict['detail']}",
             f"Route: {route['source']['host'] or '?'} → "
             f"{route['destination']['host'] or '?'}"]
    if k["items"]:
        lines.append(f"Items: {k['restored']:,}/{k['items']:,} on the "
                     f"destination ({k['created']:,} created, "
                     f"{k['exists']:,} already there, {k['missing']:,} not "
                     f"migrated)")
    lines.append(f"Scopes: {k['nodes_restored'] + k['nodes_partial']:,}/"
                 f"{k['nodes_total']:,} processed ({k['nodes_partial']:,} "
                 f"with gaps, {k['nodes_failed']:,} failed, "
                 f"{k['nodes_not_run']:,} not run)")
    if k["active_seconds"] is not None:
        lines.append(f"Restore time: {fmt_duration(k['active_seconds'])} "
                     f"over {k['runs']} run(s)")
    groups = report["failures"]["groups"][:5]
    if groups:
        lines.append("Top issues:")
        lines += [f"  - {g['what']} ({g['count']:,})" for g in groups]
    todo = [r for r in report["recommendations"]
            if r["priority"] in ("high", "medium")][:6]
    if todo:
        lines.append("Next steps:")
        lines += [f"  - {r['title']}" for r in todo]
    lines.append(f"Generated {fmt_when(report['generatedAt'])} by "
                 f"S1 Command Center {report['tool']['version']}")
    return "\n".join(lines)


def build_migration_report(runs, *, backup=None, backup_file=None,
                           integrity=None, secret_count=0, renames=None,
                           progress=None, preflight=None, preview=None,
                           validation=None, environment=None, explain=None,
                           summarize=None, cat_label=None, now=None):
    runs = _dicts(runs) or [{}]
    meta = dict(runs[-1].get("meta") or {})
    now = now or datetime.now().astimezone()
    backup_nodes = _dicts(backup)
    nodes, ledger = _merge_runs(runs)
    outcomes = build_gap_report(ledger, meta)
    node_rows = _node_rows(progress, nodes, ledger)
    node_stats = _node_stats(node_rows)
    run_list = _run_summaries(runs)
    failures = _failures(nodes, ledger, explain)
    backup_section = _backup_section(backup_nodes, backup_file, integrity,
                                     secret_count, renames, summarize,
                                     cat_label, node_rows)
    kpis = _kpis(outcomes["totals"], node_stats, run_list, failures, meta)
    report = {
        "kind": REPORT_KIND,
        "version": REPORT_VERSION,
        "generatedAt": now.isoformat(timespec="seconds"),
        "tool": {"name": "S1 Command Center", "version": APP_VERSION},
        "title": (meta.get("customer") or meta.get("dest_console")
                  or host_of(meta.get("dest_url")) or "Migration"),
        "meta": meta,
        "verdict": _verdict(meta, kpis),
        "kpis": kpis,
        "route": _route(meta, backup_section),
        "backup": backup_section,
        "restore": {"runs": run_list, "nodes": node_rows, "stats": node_stats,
                    "sites": _site_cards(node_rows),
                    "elements": [element_title(e, cat_label)
                                 for e in (meta.get("elements") or [])],
                    "snapshot": _snapshot_state(run_list)},
        "failures": failures,
        "successes": _successes(outcomes, node_rows),
        "gaps": _gaps(outcomes),
        "readiness": {"preflight": _preflight_section(preflight),
                      "preview": _preview_section(preview,
                                                  outcomes["totals"])},
        "validation": _validation_section(validation, meta, cat_label),
        "environment": dict(environment or {}),
    }
    report["log"], report["log_total"] = _log_lines(runs)
    report["timeline"] = _timeline(report, now)
    report["findings"] = _findings(report)
    report["recommendations"] = _recommendations(report)
    report["sources"] = _sources(report, progress, ledger)
    report["summary_text"] = _summary_text(report)
    return report


_PAGE_CSS = """
:root{--font:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;--radius:14px;
color-scheme:dark;--bg:#181922;--bg2:#1C1D26;--card:#262732;--card2:#2F3040;--hover:#2C2D3B;
--border:#3A3B4B;--text:#E7E7EE;--muted:#9CA3AF;--faint:#6B7280;--brand:#8B5CF6;--brand-2:#C4B5FD;
--brand-bg:rgba(139,92,246,.16);--green:#10B981;--green-bg:rgba(16,185,129,.15);--red:#F43F5E;
--red-bg:rgba(244,63,94,.15);--amber:#F59E0B;--amber-bg:rgba(245,158,11,.15);--blue:#38BDF8;
--blue-bg:rgba(56,189,248,.14);--orange:#FB923C;--rose:#F472B6;--gray:#6B7280;--track:#32333F;
--shadow:0 1px 2px rgba(0,0,0,.28),0 10px 28px rgba(0,0,0,.20)}
:root[data-theme="light"]{color-scheme:light;--bg:#F4F5F7;--bg2:#ECEEF2;--card:#FFFFFF;--card2:#F7F8FA;
--hover:#F0F1F4;--border:#D4D7DE;--text:#1A1C23;--muted:#5A6270;--faint:#8A909C;--brand:#7C3AED;
--brand-2:#6D28D9;--brand-bg:rgba(124,58,237,.10);--green:#059669;--green-bg:#D1FAE5;--red:#E11D48;
--red-bg:#FFE4E6;--amber:#B45309;--amber-bg:#FEF3C7;--blue:#0284C7;--blue-bg:#E0F2FE;--orange:#EA580C;
--rose:#DB2777;--gray:#94A3B8;--track:#E5E7EB;
--shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06)}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font:14px/1.55 var(--font);background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.wrap{max-width:1440px;margin:0 auto;padding:24px 28px 56px}
button,input,select{font:inherit;color:inherit}
a{color:var(--brand-2)}
[id]{scroll-margin-top:84px}
.hero{position:relative;overflow:hidden;border-radius:20px;padding:24px 30px 22px;margin-bottom:16px;
border:1px solid var(--border);border-top:4px solid var(--brand);box-shadow:var(--shadow);
background:radial-gradient(900px 260px at 0% 0%,var(--brand-bg),transparent 60%),linear-gradient(135deg,var(--card),var(--card2))}
.hero[data-verdict="success"]{border-top-color:var(--green)}
.hero[data-verdict="warnings"],.hero[data-verdict="stopped"]{border-top-color:var(--amber)}
.hero[data-verdict="failed"]{border-top-color:var(--red)}
.hero::after{content:"";position:absolute;right:-90px;top:-90px;width:280px;height:280px;border-radius:50%;
background:radial-gradient(circle,var(--brand-bg),transparent 70%);pointer-events:none}
.hero>*{position:relative;z-index:1}
.hero-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;color:var(--muted);font-size:13px}
.logo{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:9px;background:var(--brand);color:#fff;font-weight:800;font-size:13px}
.hero-actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:7px 12px;font-size:12.5px;
font-weight:600;cursor:pointer;color:var(--text);transition:background .15s,border-color .15s;white-space:nowrap}
.btn:hover{background:var(--hover);border-color:var(--brand)}
.btn[aria-pressed="true"]{background:var(--brand-bg);border-color:var(--brand)}
.btn-sm{padding:4px 10px;font-size:12px}
.copy-ok{color:var(--green)!important;border-color:var(--green)!important}
.copy-bad{color:var(--red)!important;border-color:var(--red)!important}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--brand-2)}
.hero h1{font-size:30px;line-height:1.2;margin:4px 0 6px;letter-spacing:-.01em;overflow-wrap:anywhere}
.hero-route{display:flex;align-items:center;gap:10px;font-size:15px;color:var(--muted);flex-wrap:wrap}
.hero-route .arrow{color:var(--brand);font-weight:700}
.hero-meta{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:14px;font-size:12.5px;color:var(--faint)}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;font-weight:700;font-size:12.5px}
.pill-success{background:var(--green-bg);color:var(--green)}
.pill-warnings,.pill-stopped{background:var(--amber-bg);color:var(--amber)}
.pill-failed{background:var(--red-bg);color:var(--red)}
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:1px;overflow-x:auto;padding:7px;margin:0 0 20px;
background:var(--bg);background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);
-webkit-backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:14px;scrollbar-width:thin}
.tab{display:inline-flex;align-items:center;gap:4px;white-space:nowrap;border:1px solid transparent;background:transparent;
border-radius:10px;padding:7px 9px;font-size:12.5px;font-weight:600;color:var(--muted);cursor:pointer;transition:background .15s,color .15s}
.tab:hover{background:var(--hover);color:var(--text)}
.tab.active{background:var(--brand);color:#fff}
.tab:focus-visible,.btn:focus-visible,.kpi.clickable:focus-visible,.chip:focus-visible,summary:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.tab-n{font-size:10.5px;font-weight:700;padding:1px 5px;border-radius:999px;background:var(--card2);color:var(--muted)}
.tab.active .tab-n{background:rgba(255,255,255,.22);color:#fff}
.tab-n.n-bad{background:var(--red-bg);color:var(--red)}
.tab-n.n-warn{background:var(--amber-bg);color:var(--amber)}
.tab-n.n-good{background:var(--green-bg);color:var(--green)}
.panel{display:none;scroll-margin-top:80px}
.panel.active{display:block;animation:fade .2s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.show-all .panel{display:block;margin-bottom:44px}
.panel-head{margin:4px 2px 16px}
.panel-head h2{font-size:21px;letter-spacing:-.01em}
.panel-head .lead{color:var(--muted);margin-top:4px;max-width:900px}
.grid{display:grid;gap:16px;margin-bottom:16px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;
box-shadow:var(--shadow);margin-bottom:16px;min-width:0}
.grid>.card{margin-bottom:0}
.card-h{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.card h3{font-size:15px}
.card h4{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:14px 0 8px}
.hint{color:var(--muted);font-size:13px;margin:-4px 0 12px}
.muted{color:var(--muted)}
.faint{color:var(--faint)}
.mono{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere}
.small{font-size:12px}
.mt{margin-top:12px}
.plain{padding-left:18px;font-size:13px;display:grid;gap:3px}
.c-green{color:var(--green)}.c-red{color:var(--red)}.c-amber{color:var(--amber)}.c-blue{color:var(--blue)}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow);min-width:0}
.kpi.clickable{cursor:pointer;transition:border-color .15s}
.kpi.clickable:hover{border-color:var(--brand)}
.kpi-l{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.kpi-v{font-size:26px;font-weight:750;margin-top:2px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi-s{font-size:12px;color:var(--faint);margin-top:2px}
.t-good .kpi-v{color:var(--green)}.t-bad .kpi-v{color:var(--red)}.t-warn .kpi-v{color:var(--amber)}
.t-info .kpi-v{color:var(--blue)}.t-brand .kpi-v{color:var(--brand-2)}
.verdict{display:flex;align-items:center;gap:18px;padding:18px 22px;border-radius:var(--radius);border:1px solid var(--border);
border-left:5px solid var(--blue);margin-bottom:16px;background:var(--card);box-shadow:var(--shadow)}
.verdict.v-success{border-left-color:var(--green)}
.verdict.v-warnings,.verdict.v-stopped{border-left-color:var(--amber)}
.verdict.v-failed{border-left-color:var(--red)}
.v-icon{font-size:22px;width:50px;height:50px;border-radius:14px;display:grid;place-items:center;flex:0 0 auto;
background:var(--blue-bg);color:var(--blue);font-weight:800}
.v-success .v-icon{background:var(--green-bg);color:var(--green)}
.v-warnings .v-icon,.v-stopped .v-icon{background:var(--amber-bg);color:var(--amber)}
.v-failed .v-icon{background:var(--red-bg);color:var(--red)}
.v-body{flex:1;min-width:0}
.v-title{font-size:18px;font-weight:750}
.v-detail{color:var(--muted);margin-top:2px}
.v-rate{text-align:right}
.v-rate-n{font-size:30px;font-weight:800;font-variant-numeric:tabular-nums}
.v-success .v-rate-n{color:var(--green)}.v-warnings .v-rate-n,.v-stopped .v-rate-n{color:var(--amber)}.v-failed .v-rate-n{color:var(--red)}
.v-rate-l{font-size:12px;color:var(--muted)}
.route{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr) auto minmax(0,1fr);gap:12px;align-items:stretch}
.hop{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:12px 14px;min-width:0}
.hop-l{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.hop-v{font-weight:700;margin-top:2px;overflow-wrap:anywhere}
.hop-s{font-size:12px;color:var(--faint);overflow-wrap:anywhere}
.hop-arrow{align-self:center;color:var(--brand);font-size:20px;font-weight:700}
.bar{display:flex;height:10px;border-radius:999px;overflow:hidden;background:var(--track);width:100%}
.bar.lg{height:14px}
.seg{display:block;height:100%}
.seg-green{background:var(--green)}.seg-blue{background:var(--blue)}.seg-red{background:var(--red)}
.seg-yellow{background:var(--amber)}.seg-orange{background:var(--orange)}.seg-rose{background:var(--rose)}
.seg-gray{background:var(--gray)}.seg-brand{background:var(--brand)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:10px;font-size:12.5px;color:var(--muted)}
.lg{display:inline-flex;align-items:center;gap:6px}
.lg b{color:var(--text);font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.donut-wrap{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.donut{position:relative;width:180px;height:180px;flex:0 0 auto}
.donut svg{display:block}
.donut-c{position:absolute;inset:0;display:grid;place-content:center;text-align:center}
.donut-v{font-size:28px;font-weight:800;font-variant-numeric:tabular-nums}
.donut-s{font-size:11.5px;color:var(--muted)}
.ring-track{stroke:var(--track)}
.ring-green{stroke:var(--green)}.ring-blue{stroke:var(--blue)}.ring-red{stroke:var(--red)}.ring-yellow{stroke:var(--amber)}
.ring-orange{stroke:var(--orange)}.ring-rose{stroke:var(--rose)}.ring-gray{stroke:var(--gray)}.ring-brand{stroke:var(--brand)}
.dlist{display:grid;gap:8px;min-width:210px;flex:1}
.drow{display:flex;align-items:center;gap:10px;font-size:13px}
.drow .n{margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums}
.drow .p{color:var(--faint);width:56px;text-align:right;font-variant-numeric:tabular-nums}
.meters{display:grid;gap:9px}
.mrow{display:grid;grid-template-columns:minmax(140px,240px) minmax(0,1fr) minmax(96px,auto);gap:12px;align-items:center;font-size:13px}
.m-l{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.m-l a{color:inherit;text-decoration:none;border-bottom:1px dashed var(--faint)}
.m-r{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap}
.scale{min-width:3px}
.findings{list-style:none;display:grid;gap:9px}
.findings li{display:grid;grid-template-columns:22px 1fr;gap:8px;align-items:start}
.fi{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:800;margin-top:1px}
.fi-good{background:var(--green-bg);color:var(--green)}.fi-warn{background:var(--amber-bg);color:var(--amber)}
.fi-bad{background:var(--red-bg);color:var(--red)}.fi-info{background:var(--blue-bg);color:var(--blue)}
.tl{position:relative;padding-left:24px}
.tl::before{content:"";position:absolute;left:8px;top:6px;bottom:6px;width:2px;background:var(--border)}
.tl-i{position:relative;padding-bottom:14px}
.tl-i:last-child{padding-bottom:0}
.tl-d{position:absolute;left:-22px;top:4px;width:14px;height:14px;border-radius:50%;background:var(--card);border:3px solid var(--brand)}
.tl-good .tl-d{border-color:var(--green)}.tl-warn .tl-d{border-color:var(--amber)}.tl-bad .tl-d{border-color:var(--red)}
.tl-t{font-weight:650}
.tl-m{font-size:12px;color:var(--faint)}
.tl-x{font-size:12.5px;color:var(--muted)}
.kv{width:100%;border-collapse:collapse}
.kv th{width:34%;text-align:left;font-weight:600;color:var(--muted);font-size:12.5px;padding:6px 12px 6px 0;vertical-align:top}
.kv td{padding:6px 0;font-size:13px;overflow-wrap:anywhere}
.kv tr+tr th,.kv tr+tr td{border-top:1px dashed var(--border)}
.mini{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}
.mini th,.mini td{padding:6px 8px;border-top:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}
.mini th:first-child,.mini td:first-child{text-align:left}
.mini thead th{border-top:none;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;font-weight:700}
.mini td.l{text-align:left}
.scroll-x{overflow-x:auto;max-width:100%}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.tag{display:inline-flex;align-items:center;gap:6px;background:var(--card2);border:1px solid var(--border);border-radius:999px;
padding:3px 10px;font-size:12px;color:var(--text);max-width:100%;overflow-wrap:anywhere}
.tag b{color:var(--muted);font-weight:700}
.badge{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;white-space:nowrap}
.badge-green{background:var(--green-bg);color:var(--green)}.badge-red{background:var(--red-bg);color:var(--red)}
.badge-yellow{background:var(--amber-bg);color:var(--amber)}.badge-blue{background:var(--blue-bg);color:var(--blue)}
.badge-gray{background:var(--card2);color:var(--muted)}
.tbl-scroll{max-height:620px;overflow:auto;border:1px solid var(--border);border-radius:12px;background:var(--card)}
.data-table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px}
.data-table thead th{position:sticky;top:0;z-index:2;background:var(--card2);color:var(--muted);font-size:11px;font-weight:700;
letter-spacing:.06em;text-transform:uppercase;text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
.data-table tbody td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
.data-table tbody tr:last-child td{border-bottom:none}
.data-table tbody tr:hover td{background:var(--hover)}
.data-table td.num,.data-table th.num{text-align:right;font-variant-numeric:tabular-nums}
.data-table td.path,.data-table td.item{font-family:var(--mono);font-size:12px;overflow-wrap:anywhere;min-width:170px}
.data-table td.why{color:var(--muted);font-size:12.5px;min-width:240px;white-space:pre-line}
.data-table td.err{color:var(--red);font-size:12.5px;min-width:240px;overflow-wrap:anywhere}
thead th.sortable{cursor:pointer;user-select:none}
thead th.sortable:hover{color:var(--text)}
thead th.sortable::after{content:" \\2195";opacity:.3;font-size:10px}
thead th.sortable[aria-sort="ascending"]::after{content:" \\2191";opacity:.9}
thead th.sortable[aria-sort="descending"]::after{content:" \\2193";opacity:.9}
tr.no-match td{color:var(--faint);text-align:center;font-style:italic}
.tbl-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 8px}
.tbl-search{background:var(--card);border:1px solid var(--border);border-radius:9px;font-size:13px;padding:7px 11px;width:260px;max-width:100%;outline:none}
.tbl-search:focus,.tbl-filter-sel:focus,.log-q:focus{border-color:var(--brand)}
.tbl-filter-sel{background:var(--card);border:1px solid var(--border);border-radius:9px;font-size:12.5px;padding:7px 9px;outline:none;cursor:pointer;max-width:240px}
.tbl-clear{background:var(--red-bg);border:1px solid transparent;color:var(--red);border-radius:9px;font-size:12px;padding:7px 11px;cursor:pointer}
.tbl-count{color:var(--faint);font-size:12px;margin-left:auto}
.tbl-chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.chip{display:inline-flex;align-items:center;gap:7px;background:var(--card);border:1px solid var(--border);color:var(--muted);
border-radius:999px;font-size:12px;font-weight:600;padding:5px 11px;cursor:pointer}
.chip:hover{color:var(--text);border-color:var(--brand)}
.chip .chip-dot{width:8px;height:8px;border-radius:50%;background:var(--gray)}
.chip .chip-n{color:var(--faint);font-weight:700}
.chip.on{color:var(--text);background:var(--brand-bg);border-color:var(--brand)}
.chip-green .chip-dot{background:var(--green)}.chip-red .chip-dot{background:var(--red)}
.chip-yellow .chip-dot{background:var(--amber)}.chip-blue .chip-dot{background:var(--blue)}
.banner{border-radius:12px;padding:12px 16px;margin-bottom:16px;border:1px solid var(--border);border-left:4px solid var(--blue);
background:var(--blue-bg);font-size:13.5px}
.banner.b-warn{border-left-color:var(--amber);background:var(--amber-bg)}
.banner.b-bad{border-left-color:var(--red);background:var(--red-bg)}
.banner.b-good{border-left-color:var(--green);background:var(--green-bg)}
.empty{text-align:center;padding:42px 20px;border:1px dashed var(--border);border-radius:var(--radius);background:var(--card)}
.empty-i{font-size:34px}
.empty-t{font-size:17px;font-weight:700;margin-top:8px}
.empty-d{color:var(--muted);margin:4px auto 0;max-width:600px}
.fail{border-left:4px solid var(--red)}
.fail.sev-warning{border-left-color:var(--amber)}
.fail.sev-info{border-left-color:var(--blue)}
.fail-h{display:flex;align-items:flex-start;gap:12px;margin-bottom:8px}
.fail-h h3{flex:1;font-size:15.5px}
.fail-n{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--red);line-height:1}
.sev-warning .fail-n{color:var(--amber)}.sev-info .fail-n{color:var(--blue)}
.fail-sub{font-size:12px;color:var(--faint)}
.fail-p{margin-top:10px}
.fail-p b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:2px}
.fail-p span{white-space:pre-line;font-size:13.5px}
.fail-actions{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
details>summary{cursor:pointer;font-weight:600;color:var(--brand-2);list-style:none;padding:6px 0}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"\\25B8";display:inline-block;margin-right:6px;transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}
.gap-el{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:4px 18px;margin-bottom:10px;box-shadow:var(--shadow)}
.gap-el[open]{padding-bottom:16px}
.gap-el>summary{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--text);padding:12px 0}
.gap-el>summary .t{font-size:14.5px;font-weight:700}
.gap-el>summary .s{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.sites{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.site{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:12px 14px;border-top:3px solid var(--green);min-width:0}
.site.so-partial,.site.so-not-run{border-top-color:var(--amber)}
.site.so-failed,.site.so-interrupted{border-top-color:var(--red)}
.site.so-skipped{border-top-color:var(--blue)}
.site-h{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:8px}
.site-t{font-weight:700;overflow-wrap:anywhere}
.site-s{font-size:12px;color:var(--faint);overflow-wrap:anywhere}
.site-m{font-size:12px;color:var(--muted);margin-top:8px}
.glist{list-style:none;display:grid;gap:5px;margin-top:4px;max-height:260px;overflow:auto}
.glist li{display:grid;grid-template-columns:10px minmax(0,1fr) auto;gap:8px;align-items:center;font-size:12.5px}
.glist li span{overflow-wrap:anywhere}
.glist .g-d{font-size:11.5px;color:var(--faint);grid-column:2/4}
.odot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--gray);flex:0 0 auto}
.od-restored{background:var(--green)}.od-partial{background:var(--amber)}.od-failed,.od-interrupted{background:var(--red)}
.od-skipped{background:var(--blue)}.od-not-run{background:var(--gray)}.od-none{background:transparent;border:1px solid var(--faint)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.tile{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:12px 14px;min-width:0}
.tile-t{font-weight:700;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tile-v{font-size:24px;font-weight:800;color:var(--green);font-variant-numeric:tabular-nums;margin:2px 0}
.tile-s{font-size:12px;color:var(--muted);margin-bottom:8px}
.tile-f{margin-top:8px}
.rec{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:14px;align-items:start;padding:14px 16px;border:1px solid var(--border);
border-radius:12px;background:var(--card);margin-bottom:10px;border-left:4px solid var(--blue);box-shadow:var(--shadow)}
.rec.p-high{border-left-color:var(--red)}.rec.p-medium{border-left-color:var(--amber)}.rec.p-low{border-left-color:var(--green)}
.rec-n{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:800;background:var(--card2);color:var(--muted)}
.rec-t{font-weight:700;font-size:14.5px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.rec-d{color:var(--muted);margin-top:3px;font-size:13.5px;overflow-wrap:anywhere}
.check{list-style:none;display:grid;gap:8px}
.check label{display:flex;gap:10px;align-items:flex-start;cursor:pointer}
.check input{margin-top:3px;accent-color:var(--brand);width:16px;height:16px;flex:0 0 auto}
.check input:checked+span{color:var(--faint);text-decoration:line-through}
.gloss{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px 18px}
.gloss>div{display:grid;grid-template-columns:110px 1fr;gap:10px;align-items:start;font-size:12.5px;color:var(--muted)}
.gloss>div>span:first-child{justify-self:start}
.log-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.seg-btns{display:inline-flex;border:1px solid var(--border);border-radius:10px;overflow:hidden;flex-wrap:wrap}
.seg-btns button{border:none;background:var(--card);padding:7px 12px;font-size:12.5px;font-weight:600;cursor:pointer;color:var(--muted)}
.seg-btns button+button{border-left:1px solid var(--border)}
.seg-btns button.on{background:var(--brand);color:#fff}
.seg-btns b{font-weight:700;opacity:.8;margin-left:4px}
.log-q{background:var(--card);border:1px solid var(--border);border-radius:9px;font-size:13px;padding:7px 11px;width:280px;max-width:100%;outline:none}
.log-count{color:var(--faint);font-size:12px;margin-left:auto}
.log{font-family:var(--mono);font-size:12.3px;line-height:1.5;background:var(--bg2);border:1px solid var(--border);border-radius:12px;
max-height:72vh;overflow:auto;padding:8px 0}
.ln{display:grid;grid-template-columns:62px minmax(0,1fr);padding-right:14px}
.ln:hover{background:var(--hover)}
.ln .no{color:var(--faint);text-align:right;padding-right:12px;user-select:none}
.ln .tx{white-space:pre-wrap;overflow-wrap:anywhere}
.lv-error .tx{color:var(--red)}.lv-warn .tx{color:var(--amber)}.lv-ok .tx{color:var(--green)}
.lv-head .tx{color:var(--brand-2);font-weight:700;padding:6px 0}
.tree ul{list-style:none;margin:4px 0 6px 18px;display:grid;gap:4px}
.tree>ul{margin-left:0}
.tree li{font-size:13px}
.tree .row{display:inline-flex;align-items:center;gap:8px}
.tree summary{color:var(--text);font-weight:600}
.tree .cnt{color:var(--faint);font-size:12px;font-weight:400}
.summary{white-space:pre-wrap;font-family:var(--mono);font-size:12.3px;background:var(--bg2);border:1px solid var(--border);
border-radius:10px;padding:12px 14px;max-height:340px;overflow:auto}
footer{margin-top:28px;padding-top:16px;border-top:1px solid var(--border);color:var(--faint);font-size:12px;text-align:center}
@media (max-width:1300px){.tab .ti{display:none}}
@media (max-width:1100px){.g4{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:860px){.g2,.g3{grid-template-columns:minmax(0,1fr)}.route{grid-template-columns:minmax(0,1fr)}
.hop-arrow{transform:rotate(90deg);justify-self:center}.mrow{grid-template-columns:120px minmax(0,1fr) auto}.wrap{padding:16px}
.rec{grid-template-columns:30px minmax(0,1fr)}.rec>div:last-child{grid-column:2}}
@media (max-width:560px){.g4{grid-template-columns:minmax(0,1fr)}.verdict{flex-wrap:wrap}.v-rate{text-align:left;flex-basis:100%}.hero h1{font-size:24px}}
@media (prefers-reduced-motion:reduce){.panel.active{animation:none}html{scroll-behavior:auto}}
@media print{
:root,:root[data-theme="dark"],:root[data-theme="light"]{color-scheme:light;--bg:#fff;--bg2:#f6f7f9;--card:#fff;--card2:#f7f8fa;
--hover:transparent;--border:#d9dce3;--text:#111;--muted:#555;--faint:#777;--brand:#7C3AED;--brand-2:#6D28D9;--brand-bg:#F1ECFE;
--green:#047857;--green-bg:#D1FAE5;--red:#BE123C;--red-bg:#FFE4E6;--amber:#B45309;--amber-bg:#FEF3C7;--blue:#0369A1;
--blue-bg:#E0F2FE;--track:#e5e7eb;--shadow:none}
body{font-size:12px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.wrap{max-width:none;padding:0}
.tabs,.hero-actions,.no-print,.tbl-filters,.tbl-chips,.log-tools{display:none!important}
.panel{display:block!important;break-before:page;animation:none!important}
#tab-overview{break-before:auto}
.tbl-scroll,.log,.glist,.summary{max-height:none!important;overflow:visible!important}
.card,.kpi,.site,.rec,.tile,.verdict{break-inside:avoid}
.data-table thead th{position:static!important}
.hero::after{display:none}
a{color:inherit;text-decoration:none}
}
"""

_THEME_BOOT = (
    "<script>(function(){var t=null;try{t=localStorage.getItem("
    "\"s1cc-report-theme\");}catch(e){}if(t!==\"light\"&&t!==\"dark\"){"
    "t=(window.matchMedia&&window.matchMedia(\"(prefers-color-scheme: "
    "light)\").matches)?\"light\":\"dark\";}document.documentElement"
    ".setAttribute(\"data-theme\",t);})();</script>")

_PAGE_JS = """
<script>
(function () {
  var root = document.documentElement, KEY = "s1cc-report-theme";
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var panels = Array.prototype.slice.call(document.querySelectorAll(".panel"));
  var anchor = document.getElementById("nav-anchor");

  document.querySelectorAll(".tbl-scroll").forEach(function (wrap) {
    Array.prototype.slice.call(wrap.children).forEach(function (child) {
      if (child.classList.contains("tbl-filters") ||
          child.classList.contains("tbl-chips")) {
        wrap.parentNode.insertBefore(child, wrap);
      }
    });
  });

  function showAll() { return document.body.classList.contains("show-all"); }
  function toTop() {
    if (!anchor || showAll()) return;
    var y = anchor.getBoundingClientRect().top + window.pageYOffset;
    if (window.pageYOffset > y) window.scrollTo(0, y);
  }
  function show(id, focus) {
    if (!document.getElementById("tab-" + id)) id = "overview";
    panels.forEach(function (p) {
      p.classList.toggle("active", p.id === "tab-" + id);
    });
    tabs.forEach(function (t) {
      var on = t.getAttribute("data-tab") === id;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    if (window.history && history.replaceState) {
      try { history.replaceState(null, "", "#" + id); } catch (e) {}
    }
  }
  function goto(id) {
    show(id);
    if (showAll()) {
      var p = document.getElementById("tab-" + id);
      if (p) p.scrollIntoView({ behavior: "smooth", block: "start" });
    } else { toTop(); }
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { goto(t.getAttribute("data-tab")); });
    t.addEventListener("keydown", function (e) {
      var j = -1;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = tabs.length - 1;
      if (j < 0) return;
      e.preventDefault();
      show(tabs[j].getAttribute("data-tab"), true);
    });
  });

  function openTarget(id) {
    var d = document.getElementById(id);
    if (!d) return;
    var p = d.closest ? d.closest(".panel") : null;
    if (p && !p.classList.contains("active") && !showAll()) show(p.id.slice(4));
    for (var n = d; n; n = n.parentElement) {
      if (n.tagName === "DETAILS") n.open = true;
    }
    setTimeout(function () {
      d.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 40);
  }

  function flash(btn, ok) {
    if (!btn) return;
    var label = btn.getAttribute("data-label") || btn.textContent;
    btn.setAttribute("data-label", label);
    btn.textContent = ok ? "Copied \\u2713" : "Copy failed";
    btn.classList.add(ok ? "copy-ok" : "copy-bad");
    setTimeout(function () {
      btn.textContent = label;
      btn.classList.remove("copy-ok", "copy-bad");
    }, 1600);
  }
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
    return ok;
  }
  function copy(text, btn) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        function () { flash(btn, true); },
        function () { flash(btn, fallbackCopy(text)); });
    } else {
      flash(btn, fallbackCopy(text));
    }
  }
  function logText() {
    var out = [];
    document.querySelectorAll("#log .ln").forEach(function (l) {
      if (l.style.display !== "none") out.push(l.querySelector(".tx").textContent);
    });
    return out.join("\\n");
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest
      ? e.target.closest("[data-goto],[data-open],[data-copy],[data-copy-log]")
      : null;
    if (!el) return;
    if (el.hasAttribute("data-goto")) {
      e.preventDefault();
      goto(el.getAttribute("data-goto"));
      return;
    }
    if (el.hasAttribute("data-open")) {
      e.preventDefault();
      openTarget(el.getAttribute("data-open"));
      return;
    }
    if (el.hasAttribute("data-copy")) {
      var src = document.getElementById(el.getAttribute("data-copy"));
      if (src) copy(src.textContent, el);
      return;
    }
    copy(logText(), el);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var el = e.target.closest ? e.target.closest("[data-goto][role=button]") : null;
    if (!el) return;
    e.preventDefault();
    el.click();
  });

  var themeBtn = document.getElementById("btn-theme");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
  });
  var printBtn = document.getElementById("btn-print");
  if (printBtn) printBtn.addEventListener("click", function () { window.print(); });
  var allBtn = document.getElementById("btn-all");
  if (allBtn) allBtn.addEventListener("click", function () {
    var on = document.body.classList.toggle("show-all");
    allBtn.setAttribute("aria-pressed", on ? "true" : "false");
  });

  var reopened = [];
  window.addEventListener("beforeprint", function () {
    reopened = Array.prototype.filter.call(
      document.querySelectorAll("details:not([open])"),
      function (d) { return !d.classList.contains("print-closed"); });
    reopened.forEach(function (d) { d.open = true; });
  });
  window.addEventListener("afterprint", function () {
    reopened.forEach(function (d) { d.open = false; });
    reopened = [];
  });

  var log = document.getElementById("log");
  if (log) {
    var lines = Array.prototype.slice.call(log.querySelectorAll(".ln"));
    var level = "all", needle = "", timer = null;
    var qbox = document.getElementById("log-q");
    var count = document.getElementById("log-count");
    var applyLog = function () {
      var shown = 0;
      lines.forEach(function (l) {
        var ok = (level === "all" || l.getAttribute("data-lv") === level) &&
          (!needle || l.textContent.toLowerCase().indexOf(needle) !== -1);
        l.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      if (count) {
        count.textContent = shown === lines.length
          ? lines.length.toLocaleString() + " lines"
          : shown.toLocaleString() + " of " + lines.length.toLocaleString();
      }
    };
    var levelBtns = document.querySelectorAll("[data-lv-btn]");
    levelBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        level = b.getAttribute("data-lv-btn");
        levelBtns.forEach(function (o) {
          o.classList.toggle("on", o === b);
          o.setAttribute("aria-pressed", o === b ? "true" : "false");
        });
        applyLog();
      });
    });
    if (qbox) qbox.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        needle = qbox.value.trim().toLowerCase();
        applyLog();
      }, 120);
    });
    applyLog();
  }

  window.addEventListener("hashchange", function () {
    show((location.hash || "").replace(/^#/, "") || "overview");
  });
  show((location.hash || "").replace(/^#/, "") || "overview");
})();
</script>
"""

_OUTCOME_HELP = {
    "restored": "Every item for the scope landed on the destination.",
    "partial": "The scope was processed, but some of its items did not land "
               "— the Gaps tab names them.",
    "failed": "The scope errored, or could not be created on the destination.",
    "interrupted": "The run stopped while this scope was in progress.",
    "skipped": "Deliberately skipped — for example a deleted or expired "
               "source scope.",
    "not run": "Never reached — the run stopped first. Resume finishes it.",
}
_RUN_BADGES = {"completed": "green", "stopped": "yellow", "aborted": "red",
               "unfinished": "blue"}
_SEVERITY_BADGES = {"critical": ("Critical", "red"), "error": ("Error", "red"),
                    "warning": ("Warning", "yellow"),
                    "warn": ("Warning", "yellow"),
                    "info": ("Safe to ignore", "blue")}
_PRIORITY_BADGES = {"high": ("Do now", "red"), "medium": ("Soon", "yellow"),
                    "low": ("Good to know", "green"), "info": ("FYI", "blue")}
_CHECK_BADGES = {"pass": ("Pass", "green"), "warn": ("Warning", "yellow"),
                 "fail": ("Fail", "red"), "info": ("Info", "blue")}
_TONE_ICONS = {"good": "✓", "warn": "!", "bad": "✕", "info": "i"}
_LEVEL_ROWS = (("global", "Global"), ("account", "Accounts"),
               ("site", "Sites"), ("group", "Groups"))
_TAB_TITLES = {"overview": "Overview", "backup": "Backup",
               "restore": "Restore", "failures": "Failures",
               "landed": "What landed", "gaps": "Gaps",
               "readiness": "Readiness", "validation": "Validation",
               "next": "Next steps", "log": "Log", "about": "About"}
_TAB_LEADS = {
    "overview": "The outcome at a glance — what moved, what didn't, and what "
                "to do next.",
    "backup": "What was captured from the source console, how the backup run "
              "went, and whether the file is sound.",
    "restore": "How the restore went, site by site and scope by scope.",
    "failures": "Every item the destination rejected, grouped by cause, with "
                "a plain-English explanation and the fix.",
    "landed": "Everything that is now on the destination — created by this "
              "migration or already there.",
    "gaps": "Item-by-item reconciliation: for every element, what landed and "
            "what didn't, by name and with the reason.",
    "readiness": "The checks run before the restore, and how the prediction "
                 "compared with what happened.",
    "validation": "A live comparison of the source and destination consoles, "
                  "scope by scope.",
    "next": "What to do now, in priority order.",
    "log": "The full operation log of the restore.",
    "about": "How this report was made and what the terms mean.",
}


def _e(value):
    return _esc(value)


def _cls(value):
    return (re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
            or "none")


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value in (None, "") else _e(value)
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def _badge(text, color):
    return f'<span class="badge badge-{color}">{_e(text)}</span>'


def _status_badge(status):
    return _badge(STATUS_LABELS.get(status, status or "?"),
                  STATUS_BADGES.get(status, "gray"))


def _outcome_badge(outcome):
    return _badge(OUTCOME_LABELS.get(outcome, outcome or "?"),
                  OUTCOME_BADGES.get(outcome, "gray"))


def _kpi(label, value, sub="", tone="", goto=""):
    cls = "kpi" + (f" t-{tone}" if tone else "") + (" clickable" if goto
                                                     else "")
    attrs = (f' data-goto="{_e(goto)}" role="button" tabindex="0"'
             if goto else "")
    sub_html = f'<div class="kpi-s">{_e(sub)}</div>' if sub else ""
    return (f'<div class="{cls}"{attrs}><div class="kpi-l">{_e(label)}</div>'
            f'<div class="kpi-v">{_e(value)}</div>{sub_html}</div>')


def _grid(cols, items):
    return f'<div class="grid g{cols}">' + "".join(items) + "</div>"


def _kv(rows):
    body = "".join(f"<tr><th>{_e(label)}</th><td>{html}</td></tr>"
                   for label, html in rows if html not in (None, ""))
    if not body:
        return '<p class="muted">Not recorded.</p>'
    return f'<table class="kv">{body}</table>'


def _card(title, body, cls="", hint="", actions="", anchor=""):
    head = (f'<div class="card-h"><h3>{_e(title)}</h3>{actions}</div>'
            if title or actions else "")
    hint_html = f'<p class="hint">{hint}</p>' if hint else ""
    ident = f' id="{_e(anchor)}"' if anchor else ""
    return f'<div class="card {cls}"{ident}>{head}{hint_html}{body}</div>'


def _banner(tone, html):
    return f'<div class="banner b-{tone}">{html}</div>'


def _empty(icon, title, text):
    return (f'<div class="empty"><div class="empty-i">{icon}</div>'
            f'<div class="empty-t">{_e(title)}</div>'
            f'<div class="empty-d">{_e(text)}</div></div>')


def _list(items):
    return ('<ul class="plain">'
            + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>")


def _bar(segments, cls=""):
    total = sum(value for _, value, _ in segments if value > 0)
    parts = []
    for label, value, color in segments:
        if value > 0 and total:
            width = 100.0 * value / total
            parts.append(f'<span class="seg seg-{color}" '
                         f'style="width:{width:.3f}%" '
                         f'title="{_e(label)}: {value:,}"></span>')
    return f'<div class="bar {cls}">' + "".join(parts) + "</div>"


def _solid(color="brand"):
    return (f'<div class="bar"><span class="seg seg-{color}" '
            f'style="width:100%"></span></div>')


def _scaled(inner, value, maximum):
    width = 100.0 * value / maximum if maximum else 0.0
    return (f'<div class="scale" style="width:{max(width, 0.5):.2f}%">'
            f'{inner}</div>')


def _legend(segments):
    items = "".join(f'<span class="lg"><i class="dot seg-{color}"></i>'
                    f'{_e(label)} <b>{value:,}</b></span>'
                    for label, value, color in segments if value)
    return f'<div class="legend">{items}</div>' if items else ""


def _donut(segments, center, caption):
    total = sum(value for _, value, _ in segments if value > 0)
    size, stroke = 180, 24
    radius = (size - stroke) / 2
    circ = 2 * math.pi * radius
    mid = size / 2
    rings = [f'<circle cx="{mid:g}" cy="{mid:g}" r="{radius:g}" fill="none" '
             f'class="ring-track" stroke-width="{stroke}"/>']
    offset = 0.0
    for label, value, color in segments:
        if value <= 0 or not total:
            continue
        length = circ * value / total
        rings.append(
            f'<circle cx="{mid:g}" cy="{mid:g}" r="{radius:g}" fill="none" '
            f'class="ring-{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.3f} {circ - length:.3f}" '
            f'stroke-dashoffset="{-offset:.3f}" '
            f'transform="rotate(-90 {mid:g} {mid:g})">'
            f'<title>{_e(label)}: {value:,}</title></circle>')
        offset += length
    return (f'<div class="donut"><svg viewBox="0 0 {size} {size}" '
            f'width="{size}" height="{size}" role="img" '
            f'aria-label="{_e(caption)}">' + "".join(rings) + "</svg>"
            + f'<div class="donut-c"><div class="donut-v">{_e(center)}</div>'
            + f'<div class="donut-s">{_e(caption)}</div></div></div>')


def _meters(rows):
    if not rows:
        return '<p class="muted">Nothing to show.</p>'
    body = "".join(f'<div class="mrow"><div class="m-l">{label}</div>'
                   f'<div class="m-b">{bar}</div>'
                   f'<div class="m-r">{right}</div></div>'
                   for label, bar, right in rows)
    return f'<div class="meters">{body}</div>'


def _table(headers, rows, empty="Nothing to show."):
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    head = "".join(f'<th class="{cls}">{_e(label)}</th>' if cls
                   else f"<th>{_e(label)}</th>" for label, cls in headers)
    return ('<div class="tbl-scroll"><table class="data-table"><thead><tr>'
            + head + "</tr></thead><tbody>" + "".join(rows)
            + "</tbody></table></div>")


def _tr(*cells):
    out = []
    for cell in cells:
        html, cls = cell if isinstance(cell, tuple) else (cell, "")
        out.append(f'<td class="{cls}">{html}</td>' if cls
                   else f"<td>{html}</td>")
    return "<tr>" + "".join(out) + "</tr>"


def _tags(items, empty="None recorded."):
    items = [i for i in items if i]
    if not items:
        return f'<p class="muted">{_e(empty)}</p>'
    return ('<div class="chips">'
            + "".join(f'<span class="tag">{_e(i)}</span>' for i in items)
            + "</div>")


def _copy_button(target, label="Copy"):
    return (f'<button type="button" class="btn btn-sm no-print" '
            f'data-copy="{_e(target)}">{_e(label)}</button>')


def _goto_button(tab, label=""):
    text = label or f"Open {_TAB_TITLES.get(tab, tab)} →"
    return (f'<button type="button" class="btn btn-sm no-print" '
            f'data-goto="{_e(tab)}">{_e(text)}</button>')


def _hidden_text(ident, text):
    return f'<pre hidden id="{_e(ident)}">{_e(text)}</pre>'


def _scroll_x(html):
    return f'<div class="scroll-x">{html}</div>'


def _mono(text, cls="mono"):
    return f'<span class="{cls}">{_e(text)}</span>' if text else ""


def _path_label(path):
    return str(path or "") or "Global"


def _elem_label(key):
    return "Scope" if key == "(node)" else element_title(key)


def _levels_text(levels):
    if not isinstance(levels, dict) or not levels:
        return ""
    names = [str(k).replace("_", " ").capitalize()
             for k, v in levels.items() if v]
    return ", ".join(names) or "None"


def _filters_text(filters):
    if not isinstance(filters, dict) or not filters:
        return ""
    bits = [f"{k} = {v}" for k, v in filters.items() if v]
    return " · ".join(bits) or "Everything"


def _types_text(types):
    words = {"global": "global", "account": "account", "site": "site",
             "group": "group"}
    bits = []
    for key in list(words) + [k for k in types if k not in words]:
        count = types.get(key, 0)
        if count:
            plural = "" if count == 1 or key == "global" else "s"
            bits.append(f"{count:,} {words.get(key, key)}{plural}")
    return " · ".join(bits)


def _item_segments(k):
    return [("Created", k["created"], "green"),
            ("Already there", k["exists"], "blue"),
            ("Failed", k["failed"], "red"),
            ("Skipped", k["skipped"], "yellow"),
            ("Manual", k["manual"], "orange"),
            ("Not in backup", k["not_attempted"], "rose")]


def _node_segments(counts):
    return [(label, counts.get(key, 0), seg)
            for key, label, _, seg in NODE_OUTCOMES]


def _hero(r):
    verdict, route = r["verdict"], r["route"]
    source = route["source"]["host"] or "Source console"
    dest = (route["destination"]["name"] or route["destination"]["host"]
            or "Destination console")
    key = _e(verdict["key"])
    return (
        f'<header class="hero" data-verdict="{key}"><div class="hero-top">'
        '<div class="brand"><span class="logo">S1</span>S1 Command Center'
        '</div><div class="hero-actions no-print">'
        '<button type="button" class="btn" id="btn-all" '
        'aria-pressed="false">☰ All sections</button>'
        '<button type="button" class="btn" id="btn-print">🖨 Print / PDF'
        '</button><button type="button" class="btn" id="btn-theme">'
        '◐ Light / dark</button></div></div>'
        '<div class="eyebrow">Migration report</div>'
        f'<h1>{_e(r["title"])}</h1><div class="hero-route">'
        f'<span>{_e(source)}</span><span class="arrow">→</span>'
        f'<span>{_e(dest)}</span></div><div class="hero-meta">'
        f'<span class="pill pill-{key}">{_e(verdict["icon"])} '
        f'{_e(verdict["label"])}</span>'
        f'<span>Generated {_e(fmt_when(r["generatedAt"]))}</span>'
        f'<span>S1 Command Center {_e(r["tool"]["version"])}</span>'
        '</div></header>')


def _route_card(r):
    route = r["route"]
    src, bk, dst = route["source"], route["backup"], route["destination"]

    def hop(label, value, sub):
        return (f'<div class="hop"><div class="hop-l">{_e(label)}</div>'
                f'<div class="hop-v">{_e(value)}</div>'
                f'<div class="hop-s">{_e(sub)}</div></div>')

    bk_bits = []
    if bk["taken"]:
        bk_bits.append(f"taken {fmt_when(bk['taken'])}")
    if bk["nodes"]:
        bk_bits.append(f"{bk['nodes']:,} scopes")
    dst_bits = []
    if dst["name"] and dst["host"]:
        dst_bits.append(dst["host"])
    if dst["customer"] and dst["customer"] != dst["name"]:
        dst_bits.append(f"customer {dst['customer']}")
    arrow = '<div class="hop-arrow">→</div>'
    body = (hop("Source console", src["host"] or "Unknown",
                f"Console {src['version']}" if src["version"] else src["url"])
            + arrow
            + hop("Backup file", bk["name"] or "Backup", " · ".join(bk_bits))
            + arrow
            + hop("Destination console", dst["name"] or dst["host"]
                  or "Unknown", " · ".join(dst_bits)))
    return _card("", f'<div class="route">{body}</div>')


def _timeline_html(events):
    if not events:
        return '<p class="muted">No timestamps were recorded.</p>'
    items, previous = [], None
    for event in events:
        moment = parse_when(event["at"])
        gap = ""
        if previous is not None and moment is not None:
            delta = (moment - previous).total_seconds()
            if delta >= 1:
                gap = f" · +{fmt_duration(delta)}"
        previous = moment or previous
        detail = (f'<div class="tl-x">{_e(event["detail"])}</div>'
                  if event["detail"] else "")
        items.append(
            f'<div class="tl-i tl-{_cls(event["tone"])}">'
            f'<span class="tl-d"></span>'
            f'<div class="tl-t">{_e(event["icon"])} {_e(event["title"])}</div>'
            f'<div class="tl-m">{_e(fmt_when(event["at"], True))}{_e(gap)}'
            f'</div>{detail}</div>')
    return '<div class="tl">' + "".join(items) + "</div>"


def _panel_overview(r):
    k, verdict = r["kpis"], r["verdict"]
    rate = "—" if k["success_rate"] is None else f"{k['success_rate']:g}%"
    parts = [
        f'<div class="verdict v-{_cls(verdict["key"])}">'
        f'<div class="v-icon">{_e(verdict["icon"])}</div>'
        f'<div class="v-body"><div class="v-title">{_e(verdict["label"])}'
        f'</div><div class="v-detail">{_e(verdict["detail"])}</div></div>'
        f'<div class="v-rate"><div class="v-rate-n">{_e(rate)}</div>'
        f'<div class="v-rate-l">of items on the destination</div></div></div>',
        _route_card(r)]
    missing_bits = [f"{n:,} {label}" for label, n in (
        ("failed", k["failed"]), ("skipped", k["skipped"]),
        ("manual", k["manual"]), ("not in backup", k["not_attempted"])) if n]
    done = k["nodes_restored"] + k["nodes_partial"]
    groups = r["failures"]["groups"]
    backup = r["backup"]
    backup_sub = f"{backup['node_count']:,} scopes"
    if backup["taken"]:
        backup_sub += f" · {fmt_when(backup['taken'])}"
    parts.append(_grid(4, [
        _kpi("On the destination", f"{k['restored']:,}/{k['items']:,}",
             f"{rate} of the items in scope",
             "warn" if k["missing"] else "good", "landed"),
        _kpi("Created", f"{k['created']:,}",
             "new items written by this migration", "good", "landed"),
        _kpi("Already there", f"{k['exists']:,}",
             "matched on the destination, left as is", "info", "landed"),
        _kpi("Not migrated", f"{k['missing']:,}",
             " · ".join(missing_bits) or "nothing is missing",
             "bad" if k["failed"] else ("warn" if k["missing"] else "good"),
             "gaps"),
        _kpi("Scopes processed", f"{done:,}/{k['nodes_total']:,}",
             f"{k['nodes_partial']:,} with gaps · {k['nodes_failed']:,} "
             f"failed · {k['nodes_not_run']:,} not run",
             "good" if done == k["nodes_total"] else "warn", "restore"),
        _kpi("Failures", f"{k['failures']:,}",
             f"{len(groups)} kind(s) of error" if groups
             else "the destination accepted everything",
             "bad" if k["failures"] else "good", "failures"),
        _kpi("Restore time", fmt_duration(k["active_seconds"]),
             f"{k['runs']} run(s)", "brand", "restore"),
        _kpi("Backup", f"{backup['item_total']:,} items", backup_sub,
             "brand", "backup"),
    ]))
    segments = _item_segments(k)
    total = sum(n for _, n, _ in segments)
    if total:
        rows = "".join(
            f'<div class="drow"><i class="dot seg-{color}"></i>{_e(label)}'
            f'<span class="n">{n:,}</span>'
            f'<span class="p">{pct(n, total) or 0:g}%</span></div>'
            for label, n, color in segments)
        donut_body = (f'<div class="donut-wrap">'
                      f'{_donut(segments, rate, "on the destination")}'
                      f'<div class="dlist">{rows}</div></div>')
    else:
        donut_body = '<p class="muted">No items were handled.</p>'
    donut = _card("Item outcomes", donut_body, hint=_e(
        "Every item the restore handled, by what happened to it. Inherited "
        "and empty entries are left out — they are not gaps."))
    stats = r["restore"]["stats"]
    node_segments = _node_segments(stats["counts"])
    level_rows = []
    for key, label in _LEVEL_ROWS:
        tally = stats["by_type"].get(key)
        if not tally:
            continue
        failed = tally.get("failed", 0) + tally.get("interrupted", 0)
        idle = tally.get("skipped", 0) + tally.get("not run", 0)
        level_rows.append(
            f"<tr><td>{label}</td><td>{tally['total']:,}</td>"
            f'<td class="c-green">{tally.get("restored", 0):,}</td>'
            f'<td class="c-amber">{tally.get("partial", 0):,}</td>'
            f'<td class="c-red">{failed:,}</td><td>{idle:,}</td></tr>')
    level_table = ""
    if level_rows:
        level_table = _scroll_x(
            '<table class="mini"><thead><tr><th>Level</th>'
            "<th>Total</th><th>Restored</th><th>With gaps</th>"
            "<th>Failed</th><th>Skipped / not run</th></tr></thead>"
            "<tbody>" + "".join(level_rows) + "</tbody></table>")
    scopes = _card("Scope outcomes",
                   _bar(node_segments, "lg") + _legend(node_segments)
                   + level_table, actions=_goto_button("restore"))
    parts.append(_grid(2, [donut, scopes]))
    finding_items = "".join(
        f'<li><span class="fi fi-{_cls(item["tone"])}">'
        f'{_TONE_ICONS.get(item["tone"], "•")}</span>'
        f'<span>{_e(item["text"])}</span></li>' for item in r["findings"])
    findings = _card("Key findings",
                     f'<ul class="findings">{finding_items}</ul>'
                     if finding_items else
                     '<p class="muted">Nothing notable.</p>')
    parts.append(_grid(2, [findings,
                           _card("Timeline", _timeline_html(r["timeline"]))]))
    index = {e["key"]: i for i, e in enumerate(r["gaps"]["elements"])}
    elements = sorted((e for e in r["gaps"]["elements"]
                       if e["key"] != "(node)" and e["total"]),
                      key=lambda e: (-e["missing"], -e["total"],
                                     e["title"].lower()))
    top = elements[:12]
    maximum = max((e["total"] for e in top), default=0)
    rows = []
    for element in top:
        counts = element["counts"]
        segments = [("Created", counts.get("created", 0), "green"),
                    ("Already there", counts.get("exists", 0), "blue"),
                    ("Not migrated", element["missing"], "red")]
        label = (f'<a href="#" data-open="gap-el-{index[element["key"]]}" '
                 f'title="{_e(element["title"])}">{_e(element["title"])}</a>')
        right = f'{element["restored"]:,}/{element["total"]:,} '
        right += (f'<span class="c-red">−{element["missing"]:,}</span>'
                  if element["missing"] else '<span class="c-green">✓</span>')
        rows.append((label, _scaled(_bar(segments), element["total"],
                                    maximum), right))
    if rows:
        more = ""
        if len(elements) > len(top):
            more = (f'<p class="hint mt">+{len(elements) - len(top)} more '
                    f'element(s) in the Gaps tab.</p>')
        parts.append(_card(
            "By element", _meters(rows) + more,
            hint=_e("On the destination vs not migrated, per element. Click "
                    "a name for its item list."),
            actions=_goto_button("gaps")))
    parts.append(_card(
        "Share the outcome",
        f'<pre class="summary" id="summary-text">{_e(r["summary_text"])}</pre>',
        hint=_e("A plain-text summary for an email, a ticket or a chat."),
        actions=_copy_button("summary-text", "Copy summary")))
    return "".join(parts)


def _tree_dot(entry):
    outcome = (entry or {}).get("outcome") or ""
    title = OUTCOME_LABELS.get(outcome, "Not in restore scope")
    return (f'<i class="odot od-{_cls(outcome) if outcome else "none"}" '
            f'title="{_e(title)}"></i>')


def _tree_html(tree):
    out = []
    for node in tree["global"]:
        out.append(f'<li><span class="row">{_tree_dot(node)}Global '
                   f'<span class="cnt">{node["items"]:,} items</span>'
                   f'</span></li>')
    accounts = tree["accounts"]
    for account in accounts:
        sites_html = []
        for site in account["sites"]:
            groups = site["groups"]
            own = (site["node"] or {}).get("items", 0)
            label = (f'<span class="row">{_tree_dot(site["node"])}'
                     f'{_e(site["name"] or "(unnamed site)")} '
                     f'<span class="cnt">{len(groups):,} group(s) · '
                     f'{own:,} items</span></span>')
            if groups:
                leaves = "".join(
                    f'<li><span class="row">{_tree_dot(g)}{_e(g["name"])} '
                    f'<span class="cnt">{g["items"]:,} items</span></span>'
                    f'</li>' for g in groups)
                sites_html.append(f"<li><details><summary>{label}</summary>"
                                  f"<ul>{leaves}</ul></details></li>")
            else:
                sites_html.append(f"<li>{label}</li>")
        own = (account["node"] or {}).get("items", 0)
        label = (f'<span class="row">{_tree_dot(account["node"])}'
                 f'{_e(account["name"] or "(unnamed account)")} '
                 f'<span class="cnt">{len(account["sites"]):,} site(s) · '
                 f'{own:,} items</span></span>')
        if sites_html:
            open_attr = " open" if len(accounts) <= 3 else ""
            out.append(f"<li><details{open_attr}><summary>{label}</summary>"
                       f"<ul>{''.join(sites_html)}</ul></details></li>")
        else:
            out.append(f"<li>{label}</li>")
    if not out:
        return '<p class="muted">No scopes.</p>'
    return '<div class="tree"><ul>' + "".join(out) + "</ul></div>"


def _tree_legend():
    bits = "".join(f'<span class="lg"><i class="odot od-{_cls(key)}"></i>'
                   f'{_e(label)}</span>' for key, label, _, _ in NODE_OUTCOMES)
    return (f'<div class="legend" style="margin:0 0 12px">{bits}'
            f'<span class="lg"><i class="odot od-none"></i>Not in restore '
            f'scope</span></div>')


def _panel_backup(r):
    b = r["backup"]
    if not b["node_count"]:
        return _empty("📦", "No backup in this report",
                      "The backup file the restore used was not available "
                      "when this report was built, so the backup details "
                      "are missing.")
    parts = []
    if not b["has_run_record"]:
        parts.append(_banner(
            "info", "<b>Older backup file.</b> It was taken before S1 "
            "Command Center recorded backup run details, so timing, operator "
            "and per-element read results are not available. The scope and "
            "contents below come from the file itself."))
    if b["snapshot"]:
        parts.append(_banner(
            "info", "<b>This file is a pre-restore snapshot</b> of a "
            "destination console, not a backup of the source."))
    if b["cancelled"]:
        parts.append(_banner(
            "warn", "<b>The backup was stopped before it finished.</b> "
            "Scopes after the stop point are not in the file."))
    reads = b["reads"]
    integrity = b["integrity"] or {}
    element_types = sum(1 for e in b["inventory"] if not e["presence"])
    if reads["recorded"]:
        read_kpi = _kpi("Read failures", f"{reads['errors']:,}",
                        "element reads that errored" if reads["errors"]
                        else "every element read cleanly",
                        "bad" if reads["errors"] else "good")
    else:
        read_kpi = _kpi("Read failures", "—", "not recorded in this file")
    parts.append(_grid(4, [
        _kpi("Scopes in file", f"{b['node_count']:,}",
             _types_text(b["types"])),
        _kpi("Items captured", f"{b['item_total']:,}",
             f"{element_types} element type(s)", "brand"),
        read_kpi,
        _kpi("Backup time", fmt_duration(b["seconds"]),
             ("stopped early" if b["cancelled"] else "completed")
             if b["has_run_record"] else "not recorded",
             "warn" if b["cancelled"] else "brand"),
    ]))
    info = b["file"]
    sha = str(info.get("sha256") or "")
    file_rows = [
        ("File", _e(info.get("name") or "")),
        ("Location", _mono(info.get("path"))),
        ("Size", _e(fmt_bytes(info.get("size")))
         if info.get("size") is not None else ""),
        ("Modified", _e(fmt_when(info.get("modified")))
         if info.get("modified") else ""),
        ("SHA-256", (f'<span class="mono small" id="backup-sha">{_e(sha)}'
                     f'</span> ' + _copy_button("backup-sha")) if sha else ""),
        ("Format", _e(b["format"])),
        ("Kind", "Pre-restore snapshot" if b["snapshot"] else "Backup"),
    ]
    outcome = ""
    if b["has_run_record"]:
        outcome = (_badge("Stopped early", "yellow") if b["cancelled"]
                   else _badge("Completed", "green"))
    scopes_text = ""
    if b["nodes_saved"] is not None:
        scopes_text = f"{_int(b['nodes_saved']):,} saved"
        if b["nodes_planned"]:
            scopes_text += f" of {_int(b['nodes_planned']):,} planned"
    run_rows = [
        ("Source console", _mono(b["url"])),
        ("Console version", _e(b["console_version"])),
        ("Started", _e(fmt_when(b["taken"], True)) if b["taken"] else ""),
        ("Finished", _e(fmt_when(b["finished"], True))
         if b["finished"] else ""),
        ("Duration", _e(fmt_duration(b["seconds"]))
         if b["seconds"] is not None else ""),
        ("Taken by", _e(b["by"])),
        ("Tool version", _e(b["tool_version"])),
        ("Outcome", outcome),
        ("Scopes", _e(scopes_text)),
        ("Scope filter", _e(_filters_text(b["filters"]))),
        ("Levels", _e(_levels_text(b["levels"]))),
        ("Secret values", _e(f"{b['secret_count']:,} (passwords, tokens or "
                             f"keys)") if b["secret_count"] else ""),
    ]
    parts.append(_grid(2, [_card("Backup file", _kv(file_rows)),
                           _card("Backup run", _kv(run_rows))]))
    if b["elements"]:
        parts.append(_card("Elements ticked for the backup",
                           _tags(b["elements"])))
    if b["inventory"]:
        listed = [e for e in b["inventory"] if not e["presence"]]
        presence = [e for e in b["inventory"] if e["presence"]]
        maximum = max((e["items"] for e in listed), default=0)
        body = _meters([
            (f'<span title="{_e(e["label"])}">{_e(e["label"])}</span>',
             _scaled(_solid(), e["items"], maximum),
             f'{e["items"]:,} <span class="faint">in {e["nodes"]:,} '
             f'scope(s)</span>') for e in listed]) if listed else ""
        if presence:
            body += ("<h4>Configuration captured</h4><div class=\"chips\">"
                     + "".join(f'<span class="tag">{_e(e["label"])} '
                               f'<b>{e["nodes"]:,} scope(s)</b></span>'
                               for e in presence) + "</div>")
        parts.append(_card("What the backup holds", body, hint=_e(
            "Items per element, added up across every scope in the file.")))
    if reads["recorded"]:
        rows = []
        for e in reads["elements"]:
            if e["errors"]:
                badge = _badge("Errors", "red")
            elif e["denied"]:
                badge = _badge("No access", "yellow")
            elif e["unsupported"] and not e["ok"]:
                badge = _badge("No API", "blue")
            else:
                badge = _badge("OK", "green")
            rows.append(_tr(_e(e["title"]), badge, (_num(e["ok"]), "num"),
                            (_num(e["items"]), "num"),
                            (_num(len(e["denied"])), "num"),
                            (_num(len(e["errors"])), "num")))
        body = _table([("Element", ""), ("Result", ""), ("Scopes read", "num"),
                       ("Items", "num"), ("No access", "num"),
                       ("Errors", "num")], rows)
        problems = ([(e, item, True) for e in reads["elements"]
                     for item in e["errors"]]
                    + [(e, item, False) for e in reads["elements"]
                       for item in e["denied"]])
        if problems:
            problem_rows = [
                _tr((_e(_path_label(item["path"])), "path"), _e(e["title"]),
                    _badge("Error", "red") if is_error
                    else _badge("No access", "yellow"),
                    (_e(item["detail"]), "err"))
                for e, item, is_error in problems]
            open_attr = " open" if len(problems) <= 20 else ""
            body += (f'<details class="mt"{open_attr}><summary>'
                     f'{len(problems):,} read problem(s), scope by scope'
                     f'</summary>'
                     + _table([("Scope", ""), ("Element", ""), ("Result", ""),
                               ("Detail", "")], problem_rows) + "</details>")
        if reads["unsupported"]:
            body += (f'<p class="hint mt">No public API on this console for: '
                     f'{_e(", ".join(reads["unsupported"]))}.</p>')
        parts.append(_card("Element reads", body, hint=_e(
            "How each element read went while the backup ran. 'No access' "
            "means the API token's role could not read it, so those items "
            "are not in the file.")))
    if b["failed_nodes"]:
        rows = [_tr((_e(_path_label(n.get("path"))), "path"),
                    _e(n.get("type") or ""), (_e(n.get("error") or ""), "err"))
                for n in b["failed_nodes"]]
        parts.append(_card(
            "Scopes that failed to back up",
            _table([("Scope", ""), ("Level", ""), ("Error", "")], rows),
            cls="fail", hint=_e("These scopes are not in the file at all.")))
    if b["integrity"] is None:
        integrity_body = '<p class="muted">The file was not checked.</p>'
    else:
        errors = list(integrity.get("errors") or [])
        warnings = list(integrity.get("warnings") or [])
        badge = (_badge("Errors", "red") if errors
                 else _badge("Warnings", "yellow") if warnings
                 else _badge("Sound", "green"))
        integrity_body = (
            f'<p>{badge} <span class="muted">'
            f'{_int(integrity.get("node_count")):,} scope(s) checked, '
            f'{_int(integrity.get("element_nodes")):,} with element data.'
            f'</span></p>')
        if errors:
            integrity_body += "<h4>Errors</h4>" + _list(errors[:50])
        if warnings:
            integrity_body += "<h4>Warnings</h4>" + _list(warnings[:50])
    side = [_card("File integrity", integrity_body)]
    if b["renames"]:
        rows = [_tr(_e(x.get("from")), _e(x.get("to")),
                    (_num(_int(x.get("count"))), "num"),
                    _e(fmt_when(x.get("at")))) for x in b["renames"]]
        side.append(_card(
            "Renamed before the restore",
            _table([("From", ""), ("To", ""), ("Scopes", "num"),
                    ("When", "")], rows),
            hint=_e("Account or site names changed in the loaded backup "
                    "before it was restored.")))
    parts.append(_grid(2, side) if len(side) > 1 else side[0])
    parts.append(_card("Structure", _tree_legend() + _tree_html(b["tree"]),
                       hint=_e("Every scope in the file, coloured by what "
                               "the restore did with it.")))
    return "".join(parts)


def _site_card_html(card):
    outcome = card["outcome"]
    bits = [f"{card['total']:,} scope(s)", f"{card['created']:,} created"]
    if card["missing"]:
        bits.append(f"{card['missing']:,} not migrated")
    if card["seconds"]:
        bits.append(fmt_duration(card["seconds"]))
    node = card["node"]
    detail = ""
    if node and node["outcome"] not in ("restored", "partial"):
        text = node["reason"] or node["detail"]
        if text:
            detail = f'<div class="site-m">{_e(text)}</div>'
    groups_html = ""
    groups = card["groups"]
    if groups:
        items = []
        for group in groups:
            extra = ""
            text = group["reason"] or group["detail"]
            if group["outcome"] != "restored" and text:
                extra = f'<span class="g-d">{_e(text)}</span>'
            items.append(f'<li><i class="odot od-{_cls(group["outcome"])}">'
                         f'</i><span>{_e(group["name"])}</span>'
                         f'{_outcome_badge(group["outcome"])}{extra}</li>')
        attention = sum(1 for g in groups if g["outcome"] != "restored")
        label = f"{len(groups):,} group(s)"
        if attention:
            label += f" · {attention:,} need attention"
        open_attr = " open" if attention and len(groups) <= 8 else ""
        groups_html = (f'<details{open_attr}><summary>{_e(label)}</summary>'
                       f'<ul class="glist">{"".join(items)}</ul></details>')
    return (f'<div class="site so-{_cls(outcome)}"><div class="site-h"><div>'
            f'<div class="site-t">{_e(card["title"])}</div>'
            f'<div class="site-s">{_e(card["sub"])}</div></div>'
            f'{_outcome_badge(outcome)}</div>'
            f'{_bar(_node_segments(card["counts"]))}'
            f'<div class="site-m">{_e(" · ".join(bits))}</div>'
            f'{detail}{groups_html}</div>')


def _panel_restore(r):
    meta, k, restore = r["meta"], r["kpis"], r["restore"]
    runs, stats = restore["runs"], restore["stats"]
    done = k["nodes_restored"] + k["nodes_partial"]
    attention = k["nodes_partial"] + k["nodes_failed"] + k["nodes_not_run"]
    mode = " · unattended" if meta.get("unattended") else ""
    parts = [_grid(4, [
        _kpi("Scopes processed", f"{done:,}/{k['nodes_total']:,}",
             f"{pct(done, k['nodes_total']) or 0:g}% of the scopes in scope",
             "good" if done == k["nodes_total"] else "warn"),
        _kpi("Fully restored", f"{k['nodes_restored']:,}",
             "every item landed", "good"),
        _kpi("Need attention", f"{attention:,}",
             f"{k['nodes_partial']:,} with gaps · {k['nodes_failed']:,} "
             f"failed · {k['nodes_not_run']:,} not run",
             "warn" if attention else "good"),
        _kpi("Restore time", fmt_duration(k["active_seconds"]),
             f"{k['runs']} run(s){mode}", "brand"),
    ])]
    first, last = runs[0], runs[-1]
    snapshot = restore["snapshot"]
    snapshot_html = {
        "saved": _badge("Saved", "green") + " "
        + _mono(snapshot.get("path"), "mono small"),
        "failed": _badge("Failed", "red") + " "
        + _mono(snapshot.get("error"), "muted"),
        "empty": _badge("Captured nothing", "yellow"),
        "off": _badge("Not taken", "gray"),
    }.get(snapshot["state"], "")
    outcome = _badge(last["outcome"].capitalize(),
                     _RUN_BADGES.get(last["outcome"], "gray"))
    dest = r["route"]["destination"]
    dest_html = _e(dest["name"] or dest["host"])
    if dest["url"]:
        dest_html += " " + _mono(dest["url"], "mono small faint")
    rows = [
        ("Destination", dest_html),
        ("Customer", _e(meta.get("customer") or "")),
        ("Source", _mono(meta.get("source_url"))),
        ("Outcome", outcome),
        ("Error", f'<span class="c-red">{_e(last["error"])}</span>'
         if last["error"] else ""),
        ("Started", _e(fmt_when(first["start"], True))
         if first["start"] else ""),
        ("Finished", _e(fmt_when(last["end"], True)) if last["end"] else ""),
        ("Restore time", _e(fmt_duration(k["active_seconds"]))
         if k["active_seconds"] is not None else ""),
        ("Runs", _e(f"{len(runs)} (stopped and resumed)" if len(runs) > 1
                    else "1")),
        ("Mode", "Unattended" if meta.get("unattended") else "Interactive"),
        ("Scope", _e(meta.get("scope") or "")),
        ("Levels", _e(_levels_text(meta.get("levels")))),
        ("Scopes in backup", _e(f"{_int(meta.get('backup_nodes')):,}")
         if meta.get("backup_nodes") else ""),
        ("Rollback snapshot", snapshot_html),
        ("Tool version", _e(meta.get("app_version") or "")),
    ]
    parts.append(_grid(2, [
        _card("Restore run", _kv(rows)),
        _card("Elements restored",
              _tags(restore["elements"], "No element list was recorded."),
              hint=_e(f"{len(restore['elements'])} element(s) ticked for "
                      f"the restore."))]))
    segments = _node_segments(stats["counts"])
    if restore["sites"]:
        grid = ('<div class="sites mt">'
                + "".join(_site_card_html(c) for c in restore["sites"])
                + "</div>")
        parts.append(_card("By site", _bar(segments, "lg")
                           + _legend(segments) + grid, hint=_e(
                               "One card per site — plus one per account and "
                               "for global — with its groups folded inside.")))
    rows = []
    for node in restore["nodes"]:
        seconds = (f"{node['seconds']:.1f}" if node["seconds"] is not None
                   else "")
        rows.append(_tr((_num(node["num"]), "num"),
                        (_e(_path_label(node["path"])), "path"),
                        _e(node["type"]), _outcome_badge(node["outcome"]),
                        (_num(node["created"]), "num"),
                        (_num(node["exists"]), "num"),
                        (_num(node["missing"]), "num"), (seconds, "num"),
                        (_e(node["reason"] or node["detail"]), "why")))
    parts.append(_card("Every scope", _table(
        [("#", "num"), ("Scope", ""), ("Level", ""), ("Status", ""),
         ("Created", "num"), ("Already there", "num"),
         ("Not migrated", "num"), ("Seconds", "num"), ("Detail", "")],
        rows, "No scopes were processed."),
        hint=_e("Search, filter by level or status, and click a column "
                "heading to sort.")))
    timed = sorted((n for n in restore["nodes"] if n["seconds"]),
                   key=lambda n: -n["seconds"])[:10]
    if timed:
        slow = _meters([
            (f'<span title="{_e(_path_label(n["path"]))}">'
             f'{_e(_path_label(n["path"]))}</span>',
             _scaled(_solid(), n["seconds"], timed[0]["seconds"]),
             _e(fmt_duration(n["seconds"]))) for n in timed])
        by_site = sorted((c for c in restore["sites"] if c["seconds"]),
                         key=lambda c: -c["seconds"])[:10]
        site_meters = _meters([
            (f'<span title="{_e(c["sub"])}">{_e(c["title"])}</span>',
             _scaled(_solid("blue"), c["seconds"], by_site[0]["seconds"]),
             _e(fmt_duration(c["seconds"]))) for c in by_site])
        parts.append(_grid(2, [_card("Slowest scopes", slow),
                               _card("Time by site", site_meters)]))
    if len(runs) > 1:
        rows = [_tr((_num(x["n"]), "num"), _e(fmt_when(x["start"], True)),
                    _e(fmt_when(x["end"], True)),
                    _e(fmt_duration(x["seconds"])),
                    _badge(x["outcome"].capitalize(),
                           _RUN_BADGES.get(x["outcome"], "gray")),
                    (_num(x["nodes"]), "num"), (_num(x["items"]), "num"),
                    (_e(x["error"]), "why")) for x in runs]
        parts.append(_card("Runs", _table(
            [("Run", "num"), ("Started", ""), ("Finished", ""),
             ("Duration", ""), ("Outcome", ""), ("Scopes", "num"),
             ("Items", "num"), ("Note", "")], rows),
            hint=_e("The restore was stopped and resumed. Each run picked up "
                    "where the previous one stopped.")))
    return "".join(parts)


def _sev_badge(severity):
    label, color = _SEVERITY_BADGES.get(
        severity, (str(severity or "error").capitalize(), "red"))
    return _badge(label, color)


def _support_text(group):
    lines = [group["what"], f"Severity: {group['severity']}",
             f"Items: {group['count']:,} in {group['nodes']:,} scope(s)"]
    if group["why"]:
        lines.append(f"Why: {group['why']}")
    if group["fix"]:
        lines.append(f"Fix: {group['fix']}")
    lines.append("")
    for item in group["items"][:SUPPORT_LINE_CAP]:
        lines.append(f"[{item['element']}] {_path_label(item['path'])} :: "
                     f"{item['name'] or '-'} :: {item['error']}")
    if group["count"] > SUPPORT_LINE_CAP:
        lines.append(f"... and {group['count'] - SUPPORT_LINE_CAP:,} more "
                     f"(see the report)")
    return "\n".join(lines)


def _panel_failures(r):
    fails = r["failures"]
    if not fails["total"]:
        return _empty("✅", "No failures",
                      "The destination accepted every item the restore sent.")
    groups = fails["groups"]
    parts = [_grid(4, [
        _kpi("Failed items", f"{fails['total']:,}",
             "rejected by the destination", "bad"),
        _kpi("Kinds of error", f"{len(groups):,}", "grouped by cause below",
             "warn"),
        _kpi("Scopes affected", f"{fails['nodes']:,}",
             f"of {r['kpis']['nodes_total']:,} processed", "warn"),
        _kpi("Elements affected", f"{fails['elements']:,}",
             "different element types", "warn"),
    ])]
    colors = {"critical": "red", "error": "red", "warning": "yellow",
              "warn": "yellow", "info": "blue"}
    maximum = max(g["count"] for g in groups)
    rows = [(f'<a href="#" data-open="fail-{i}" title="{_e(g["what"])}">'
             f'{_e(g["what"])}</a>',
             _scaled(_solid(colors.get(g["severity"], "red")), g["count"],
                     maximum), f'{g["count"]:,}')
            for i, g in enumerate(groups)]
    everything = "\n\n".join(_support_text(g) for g in groups)
    parts.append(_card(
        "Failures by cause",
        _meters(rows) + _hidden_text("fail-sup-all", everything),
        hint=_e("Click a cause to jump to its explanation and item list."),
        actions=_copy_button("fail-sup-all", "Copy all for support")))
    for i, group in enumerate(groups):
        severity = ("warning" if group["severity"] == "warn"
                    else _cls(group["severity"]))
        tags = "".join(f'<span class="tag">{_e(_elem_label(e["key"]))} '
                       f'<b>{e["count"]:,}</b></span>'
                       for e in group["elements"])
        body = (f'<div class="fail-h">{_sev_badge(group["severity"])}'
                f'<h3>{_e(group["what"])}</h3><div style="text-align:right">'
                f'<div class="fail-n">{group["count"]:,}</div>'
                f'<div class="fail-sub">in {group["nodes"]:,} scope(s)</div>'
                f'</div></div><div class="chips">{tags}</div>')
        if group["why"]:
            body += (f'<div class="fail-p"><b>Why it happened</b>'
                     f'<span>{_e(group["why"])}</span></div>')
        if group["fix"]:
            body += (f'<div class="fail-p"><b>How to fix it</b>'
                     f'<span>{_e(group["fix"])}</span></div>')
        items = [_tr((_e(_path_label(it["path"])), "path"),
                     _e(_elem_label(it["element"])), (_e(it["name"]), "item"),
                     (_e(it["error"]), "err")) for it in group["items"]]
        open_attr = " open" if group["count"] <= 10 else ""
        body += (f'<details class="mt"{open_attr}><summary>The '
                 f'{group["count"]:,} item(s)</summary>'
                 + _table([("Scope", ""), ("Element", ""), ("Item", ""),
                           ("Error", "")], items) + "</details>")
        support_id = f"fail-sup-{i}"
        body += ('<div class="fail-actions">'
                 + _copy_button(support_id, "Copy for support") + "</div>"
                 + _hidden_text(support_id, _support_text(group)))
        parts.append(f'<div class="card fail sev-{severity}" id="fail-{i}">'
                     f'{body}</div>')
    return "".join(parts)


def _panel_landed(r):
    successes, k = r["successes"], r["kpis"]
    if not k["restored"]:
        return _empty("📭", "Nothing landed",
                      "No item was created on, or matched with, the "
                      "destination in this run.")
    clean = successes["clean_nodes"]
    parts = [_grid(4, [
        _kpi("On the destination", f"{k['restored']:,}",
             f"{k['success_rate'] or 0:g}% of the items in scope", "good"),
        _kpi("Created", f"{k['created']:,}", "new items written", "good"),
        _kpi("Already there", f"{k['exists']:,}", "matched, left unchanged",
             "info"),
        _kpi("Clean scopes", f"{len(clean):,}",
             f"of {k['nodes_total']:,} — every item landed", "good"),
    ])]
    tiles = []
    for tile in successes["tiles"]:
        segments = [("Created", tile["created"], "green"),
                    ("Already there", tile["exists"], "blue"),
                    ("Not migrated", tile["missing"], "red")]
        foot = (_badge("Complete", "green") if not tile["missing"]
                else _badge(f"{tile['missing']:,} not migrated", "yellow"))
        tiles.append(
            f'<div class="tile"><div class="tile-t" title="{_e(tile["title"])}">'
            f'{_e(tile["title"])}</div><div class="tile-v">'
            f'{tile["created"]:,}</div><div class="tile-s">created · '
            f'{tile["exists"]:,} already there</div>{_bar(segments)}'
            f'<div class="tile-f">{foot}</div></div>')
    if tiles:
        parts.append(_card("By element", '<div class="tiles">'
                           + "".join(tiles) + "</div>"))
    if clean:
        shown = clean[:CLEAN_NODE_CAP]
        more = ""
        if len(clean) > len(shown):
            more = (f'<p class="hint mt">… and {len(clean) - len(shown):,} '
                    f'more.</p>')
        parts.append(_card(
            "Scopes where everything landed",
            '<div class="chips">'
            + "".join(f'<span class="tag">✓ {_e(_path_label(p))}</span>'
                      for p in shown) + "</div>" + more))
    rows = [_tr((_e(_path_label(x["node"])), "path"), _e(x["scope"]),
                _e(x["element"]), (_e(x["item"]), "item"), _e(x["kind"]),
                _status_badge(x["status"])) for x in successes["rows"]]
    note = ""
    if successes["row_total"] > len(successes["rows"]):
        note = _banner("info", _e(
            f"Showing the first {len(successes['rows']):,} of "
            f"{successes['row_total']:,} items. The Gap Report export (Excel "
            f"or CSV) lists every one."))
    parts.append(_card(
        "Every item on the destination",
        note + _table([("Scope", ""), ("Level", ""), ("Element", ""),
                       ("Item", ""), ("Type", ""), ("Status", "")], rows,
                      "No items."),
        hint=_e("Filter by status to see only what this migration created.")))
    return "".join(parts)


def _gap_row(row, with_kind=True):
    cells = [(_e(_path_label(row.get("node"))), "path"),
             _e(row.get("scope") or ""), (_e(row.get("item") or ""), "item")]
    if with_kind:
        cells.append(_e(row.get("kind") or ""))
    cells += [_status_badge(str(row.get("status") or "")),
              (_e(row.get("reason") or ""), "why")]
    return _tr(*cells)


def _panel_gaps(r):
    gaps, k = r["gaps"], r["kpis"]
    if not gaps["totals"].get("rows"):
        return _empty("🧩", "No item ledger",
                      "This restore recorded no per-item results, so gaps "
                      "cannot be listed by name.")
    parts = []
    if not k["missing"]:
        parts.append(_banner("good", "<b>No gaps.</b> Every item in scope is "
                                     "on the destination."))
    parts.append(_grid(4, [
        _kpi("Not migrated", f"{k['missing']:,}",
             f"of {k['items']:,} items in scope",
             "bad" if k["failed"] else ("warn" if k["missing"] else "good")),
        _kpi("Failed", f"{k['failed']:,}", "rejected by the destination",
             "bad" if k["failed"] else "good",
             "failures" if k["failed"] else ""),
        _kpi("Skipped or manual", f"{k['skipped'] + k['manual']:,}",
             f"{k['skipped']:,} skipped · {k['manual']:,} manual",
             "warn" if k["skipped"] + k["manual"] else "good"),
        _kpi("Not in backup", f"{k['not_attempted']:,}",
             "ticked, but never captured",
             "bad" if k["not_attempted"] else "good"),
    ]))
    rows = []
    for i, element in enumerate(gaps["elements"]):
        counts = element["counts"]
        if element["missing"]:
            severe = counts.get("failed") or counts.get("not attempted")
            status = _badge("Has gaps", "red" if severe else "yellow")
        else:
            status = _badge("Complete", "green")
        rows.append(_tr(
            f'<a href="#" data-open="gap-el-{i}">{_e(element["title"])}</a>',
            status, (_num(element["total"]), "num"),
            *[(_num(counts.get(key, 0)), "num") for key in (
                "created", "exists", "failed", "skipped", "manual",
                "not attempted")],
            (_num(element["info"]), "num")))
    parts.append(_card("Reconciliation", _table(
        [("Element", ""), ("Status", ""), ("In scope", "num"),
         ("Created", "num"), ("Already there", "num"), ("Failed", "num"),
         ("Skipped", "num"), ("Manual", "num"), ("Not in backup", "num"),
         ("Not a gap", "num")], rows),
        hint=_e("One row per element. 'Not a gap' counts inherited and empty "
                "entries — restored at another scope, or legitimately "
                "absent.")))
    for i, element in enumerate(gaps["elements"]):
        counts = element["counts"]
        chips = "".join(_badge(f"{label} {counts[key]:,}", color)
                        for key, label, color, _ in ITEM_STATUSES
                        if counts.get(key))
        if element["missing_rows"]:
            body = _table([("Scope", ""), ("Level", ""), ("Item", ""),
                           ("Type", ""), ("Status", ""), ("Reason", "")],
                          [_gap_row(x) for x in element["missing_rows"]])
        else:
            body = ('<p class="muted">Nothing missing — every item of this '
                    'element is on the destination.</p>')
        if element["info_rows"]:
            more = ""
            if element["info_total"] > len(element["info_rows"]):
                more = f" — first {len(element['info_rows']):,} shown"
            body += (f'<details class="print-closed mt"><summary>'
                     f'{element["info_total"]:,} not-a-gap item(s) — '
                     f'inherited or empty{_e(more)}</summary>'
                     + _table([("Scope", ""), ("Level", ""), ("Item", ""),
                               ("Status", ""), ("Reason", "")],
                              [_gap_row(x, False)
                               for x in element["info_rows"]])
                     + "</details>")
        open_attr = " open" if element["missing"] else ""
        parts.append(
            f'<details class="gap-el" id="gap-el-{i}"{open_attr}><summary>'
            f'<span class="t">{_e(element["title"])}</span>'
            f'<span class="faint">{element["restored"]:,}/'
            f'{element["total"]:,} on the destination</span>'
            f'<span class="s">{chips}</span></summary>{body}</details>')
    parts.append(_card("What the statuses mean", '<div class="gloss">' + "".join(
        f"<div>{_badge(label, color)}<span>{_e(desc)}</span></div>"
        for _, label, color, desc in ITEM_STATUSES) + "</div>"))
    return "".join(parts)


def _cmp_row(label, predicted, actual):
    diff = actual - predicted
    sign = "+" if diff > 0 else ""
    cls = "c-green" if diff == 0 else "c-amber"
    return (f"<tr><td>{_e(label)}</td><td>{predicted:,}</td>"
            f'<td>{actual:,}</td><td class="{cls}">{sign}{diff:,}</td></tr>')


def _panel_readiness(r):
    preflight = r["readiness"]["preflight"]
    preview = r["readiness"]["preview"]
    if not preflight and not preview:
        return _empty("🧪", "No pre-flight or preview in this session",
                      "Pre-flight checks the destination (token permissions, "
                      "licences, name clashes) and Preview predicts what a "
                      "restore will create. Run them before the next restore "
                      "and they will show up here.")
    parts = []
    if preflight:
        label, color = _CHECK_BADGES.get(
            preflight["verdict"],
            (preflight["verdict"].capitalize() or "Done", "blue"))
        counts = preflight["counts"]
        summary = " · ".join(f"{counts[key]:,} {word}" for key, word in (
            ("pass", "passed"), ("warn", "warning(s)"), ("fail", "failed"),
            ("info", "info")) if counts.get(key))
        rows = []
        for check in preflight["checks"]:
            check_label, check_color = _CHECK_BADGES.get(
                check["status"], (check["status"].capitalize(), "gray"))
            rows.append(_tr(_e(check["name"]),
                            _badge(check_label, check_color),
                            (_e(check["detail"]), "why")))
        bits = [b for b in (fmt_when(preflight["at"], True)
                            if preflight["at"] else "",
                            host_of(preflight["dest"]), summary) if b]
        head = (f'<p>{_badge(label, color)} <span class="muted">'
                f'{_e(" · ".join(bits))}</span></p>')
        parts.append(_card(
            "Pre-flight checks",
            head + '<div class="mt">'
            + _table([("Check", ""), ("Result", ""), ("Detail", "")], rows,
                     "No checks were recorded.") + "</div>",
            hint=_e("Run against the destination before anything was "
                    "written.")))
    else:
        parts.append(_banner(
            "info", "<b>Pre-flight was not run in this session.</b> It checks "
            "the token's permissions, licences and name clashes before "
            "anything is written."))
    if preview:
        compare = _scroll_x(
            '<table class="mini"><thead><tr><th></th><th>Predicted'
            '</th><th>Actual</th><th>Difference</th></tr></thead><tbody>'
            + _cmp_row("New items (created)", preview["create"],
                       preview["actual_created"])
            + _cmp_row("Already there", preview["exists"],
                       preview["actual_exists"])
            + "</tbody></table>")
        details = _kv([
            ("Previewed", _e(fmt_when(preview["at"], True))
             if preview["at"] else ""),
            ("Destination", _mono(preview["dest"])),
            ("Scopes compared", _e(f"{preview['nodes']:,}")),
            ("Not on the destination yet",
             _e(f"{preview['missing']:,} scope(s) — would be created")),
        ])
        rows = [_tr(_e(e["label"]), (_num(e["create"]), "num"),
                    (_num(e["exists"]), "num"))
                for e in preview["per_element"] if e["create"] or e["exists"]]
        parts.append(_grid(2, [
            _card("Dry-run preview", details + compare, hint=_e(
                "The preview compares item names, so the actual numbers can "
                "differ when items are renamed or fail, or when the restore "
                "covered a different scope.")),
            _card("Predicted per element", _table(
                [("Element", ""), ("New", "num"), ("Already there", "num")],
                rows, "No per-element prediction was recorded."))]))
    else:
        parts.append(_banner(
            "info", "<b>No dry-run preview in this session.</b> Preview "
            "predicts, element by element, what a restore will create and "
            "what already exists."))
    return "".join(parts)


def _value_cell(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _num(value)
    if isinstance(value, (list, tuple, dict)):
        return _num(len(value))
    return _e("" if value is None else value)


def _names_text(names, limit=10):
    text = ", ".join(names[:limit])
    if len(names) > limit:
        text += f" +{len(names) - limit:,} more"
    return text


def _panel_validation(r):
    v = r["validation"]
    parts = []
    if v["stale"]:
        parts.append(_banner(
            "warn", "<b>These results predate the restore.</b> Migration "
            "Validation ran before this restore started, so it does not "
            "reflect it — run it again."))
    if v["cancelled"]:
        parts.append(_banner("warn", "<b>Validation was stopped early</b> — "
                                     "not every scope was compared."))
    clean = not v["differing"] and not v["missing_nodes"]
    parts.append(_grid(4, [
        _kpi("Scopes compared", f"{v['nodes']:,}",
             fmt_when(v["when"]) if v["when"] else ""),
        _kpi("Identical", f"{v['identical']:,}",
             "source and destination match", "good"),
        _kpi("With differences", f"{v['differing']:,}",
             f"{v['diff_total']:,} difference(s) in total",
             "warn" if v["differing"] else "good"),
        _kpi("No match on destination", f"{len(v['missing_nodes']):,}",
             "scopes missing there", "bad" if v["missing_nodes"] else "good"),
    ]))
    parts.append(_card("Comparison", _kv([
        ("Checked", _e(fmt_when(v["when"], True)) if v["when"] else ""),
        ("Source", _mono(v["src_url"])),
        ("Destination", _mono(v["dst_url"])),
        ("Result", _badge("Identical", "green") if clean
         else _badge("Differences found", "yellow")),
    ])))
    if v["diffs"]:
        rows = []
        for diff in v["diffs"]:
            explain = "\n".join(text for text in (
                diff["what"],
                f"Why: {diff['why']}" if diff["why"] else "",
                f"Fix: {diff['fix']}" if diff["fix"] else "") if text)
            rows.append(_tr((_e(_path_label(diff["path"])), "path"),
                            _e(diff["label"]),
                            (_value_cell(diff["src"]), "num"),
                            (_value_cell(diff["dst"]), "num"),
                            (_e(_names_text(diff["missing"])), "item"),
                            (_e(_names_text(diff["extra"])), "item"),
                            (_e(explain), "why")))
        parts.append(_card("Differences", _table(
            [("Scope", ""), ("Element", ""), ("Source", "num"),
             ("Destination", "num"), ("Missing on destination", ""),
             ("Only on destination", ""), ("Explanation", "")], rows),
            hint=_e("Each row is one element in one scope whose contents "
                    "differ between the consoles.")))
    if v["missing_nodes"]:
        rows = [_tr((_e(_path_label(n["path"])), "path"), _e(n["type"]))
                for n in v["missing_nodes"]]
        parts.append(_card("Scopes with no match on the destination",
                           _table([("Scope", ""), ("Level", "")], rows)))
    return "".join(parts)


_CHECKLIST = (
    "Review every failure — fix it, or agree with the customer to accept it",
    "Recreate the manual items on the destination",
    "Run Migration Validation and review the differences",
    "Spot-check key policies, exclusions and groups in the destination "
    "console",
    "Keep the backup file and the rollback snapshot until sign-off",
    "Move the agents with Agent Migration",
    "Send this report to the customer",
)


def _panel_next(r):
    items = []
    for n, rec in enumerate(r["recommendations"], 1):
        label, color = _PRIORITY_BADGES.get(rec["priority"], ("FYI", "blue"))
        go = _goto_button(rec["tab"]) if rec["tab"] else ""
        items.append(
            f'<div class="rec p-{_cls(rec["priority"])}">'
            f'<div class="rec-n">{n}</div><div><div class="rec-t">'
            f'{_badge(label, color)}{_e(rec["title"])}</div>'
            f'<div class="rec-d">{_e(rec["detail"])}</div></div>'
            f'<div>{go}</div></div>')
    checklist = ('<ul class="check">'
                 + "".join(f'<li><label><input type="checkbox">'
                           f'<span>{_e(text)}</span></label></li>'
                           for text in _CHECKLIST) + "</ul>")
    return "".join(items) + _card(
        "Sign-off checklist", checklist,
        hint=_e("Tick as you go — ticks are not saved with the file."))


def _panel_log(r):
    lines = r["log"]
    if not lines:
        return _empty("📜", "No log",
                      "The restore did not record an operation log.")
    counts = Counter(line["level"] for line in lines)
    buttons = []
    for key, label, n in (("all", "All", len(lines)),
                          ("error", "Errors", counts["error"]),
                          ("warn", "Warnings", counts["warn"]),
                          ("ok", "Success", counts["ok"]),
                          ("info", "Info", counts["info"])):
        on = key == "all"
        buttons.append(f'<button type="button" data-lv-btn="{key}" '
                       f'class="{"on" if on else ""}" '
                       f'aria-pressed="{"true" if on else "false"}">'
                       f'{label}<b>{n:,}</b></button>')
    note = ""
    if len(lines) >= LOG_LINE_CAP:
        note = _banner("info", _e(
            f"The log is long — the first {LOG_LINE_CAP:,} lines are shown "
            f"(of {r['log_total']:,})."))
    rows = "".join(f'<div class="ln lv-{line["level"]}" '
                   f'data-lv="{line["level"]}"><span class="no">{n}</span>'
                   f'<span class="tx">{_e(line["text"])}</span></div>'
                   for n, line in enumerate(lines, 1))
    tools = ('<div class="log-tools no-print"><div class="seg-btns" '
             'role="group" aria-label="Filter the log by level">'
             + "".join(buttons) + "</div>"
             '<input type="search" class="log-q" id="log-q" '
             'placeholder="Search the log…" aria-label="Search the log">'
             '<span class="log-count" id="log-count"></span>'
             '<button type="button" class="btn btn-sm" data-copy-log="1">'
             'Copy shown lines</button></div>')
    return note + tools + f'<div class="log" id="log">{rows}</div>'


def _panel_about(r):
    env, meta = r["environment"], r["meta"]
    rows = [
        ("Report generated", _e(fmt_when(r["generatedAt"], True))),
        ("Made with", _e(f"S1 Command Center {r['tool']['version']}")),
        ("Report format", _e(f"{REPORT_KIND} v{REPORT_VERSION}")),
        ("Restore made with", _e(meta.get("app_version") or "")),
        ("Backup made with", _e(r["backup"]["tool_version"])),
        ("Platform", _e(env.get("platform") or "")),
        ("Python", _e(env.get("python") or "")),
    ]
    source_rows = "".join(
        f'<tr><td>{_e(s["name"])}</td><td class="l">'
        + (_badge("Included", "green") if s["present"]
           else _badge("Not available", "gray"))
        + f'</td><td class="l muted">{_e(s["detail"])}</td></tr>'
        for s in r["sources"])
    sources = _scroll_x('<table class="mini"><thead><tr><th>Source</th>'
                        '<th style="text-align:left">Status</th>'
                        '<th style="text-align:left">Detail</th></tr>'
                        '</thead><tbody>' + source_rows + "</tbody></table>")
    statuses = "".join(f"<div>{_badge(label, color)}<span>{_e(desc)}</span>"
                       f"</div>" for _, label, color, desc in ITEM_STATUSES)
    outcomes = "".join(f"<div>{_outcome_badge(key)}"
                       f"<span>{_e(_OUTCOME_HELP.get(key, ''))}</span></div>"
                       for key, _, _, _ in NODE_OUTCOMES)
    privacy = ("This file is self-contained: it makes no network requests "
               "and needs no internet connection. It contains scope names, "
               "item names and error messages from both consoles, so share it "
               "only with people allowed to see that configuration. It does "
               "not contain API tokens.")
    return (_grid(2, [
        _card("This report", _kv(rows)),
        _card("Data sources", sources, hint=_e(
            "What the report was built from. A missing source only leaves "
            "its section empty — it does not make the rest wrong."))])
        + _card("Item statuses", f'<div class="gloss">{statuses}</div>')
        + _card("Scope outcomes", f'<div class="gloss">{outcomes}</div>')
        + _card("Privacy", f'<p class="muted">{_e(privacy)}</p>'))


_PANELS = {
    "overview": _panel_overview, "backup": _panel_backup,
    "restore": _panel_restore, "failures": _panel_failures,
    "landed": _panel_landed, "gaps": _panel_gaps,
    "readiness": _panel_readiness, "validation": _panel_validation,
    "next": _panel_next, "log": _panel_log, "about": _panel_about,
}
_TAB_ICONS = {"overview": "📊", "backup": "📦", "restore": "🚀",
              "failures": "🛑", "landed": "✅", "gaps": "🧩",
              "readiness": "🧪", "validation": "🔎", "next": "🧭",
              "log": "📜", "about": "ℹ️"}


def _tab_specs(r):
    k, fails, backup = r["kpis"], r["failures"], r["backup"]
    recs = r["recommendations"]
    actionable = sum(1 for x in recs if x["priority"] in ("high", "medium"))
    urgent = any(x["priority"] == "high" for x in recs)
    backup_issue = bool(backup["reads"]["errors"] or backup["failed_nodes"]
                        or (backup["integrity"] or {}).get("errors"))
    specs = [
        ("overview", "", ""),
        ("backup", "!" if backup_issue else "",
         "warn" if backup_issue else ""),
        ("restore", f"{k['nodes_total']:,}", ""),
        ("failures", f"{fails['total']:,}" if fails["total"] else "✓",
         "bad" if fails["total"] else "good"),
        ("landed", f"{k['restored']:,}", "good" if k["restored"] else ""),
        ("gaps", f"{k['missing']:,}" if k["missing"] else "✓",
         "warn" if k["missing"] else "good"),
        ("readiness", "", ""),
    ]
    validation = r["validation"]
    if validation:
        issues = validation["differing"] + len(validation["missing_nodes"])
        specs.append(("validation", f"{issues:,}" if issues else "✓",
                      "warn" if issues or validation["stale"] else "good"))
    specs += [
        ("next", f"{actionable:,}" if actionable else "",
         "bad" if urgent else ("warn" if actionable else "")),
        ("log", f"{r['log_total']:,}" if r["log_total"] else "", ""),
        ("about", "", ""),
    ]
    return specs


def render_migration_report_html(report):
    nav, panels = [], []
    for i, (tab, badge, tone) in enumerate(_tab_specs(report)):
        title, icon = _TAB_TITLES[tab], _TAB_ICONS[tab]
        active = i == 0
        badge_html = ""
        if badge:
            tone_cls = f" n-{tone}" if tone else ""
            badge_html = f'<span class="tab-n{tone_cls}">{_e(badge)}</span>'
        nav.append(f'<button type="button" class="tab{" active" if active else ""}" '
                   f'role="tab" id="tabbtn-{tab}" aria-controls="tab-{tab}" '
                   f'aria-selected="{"true" if active else "false"}" '
                   f'tabindex="{0 if active else -1}" data-tab="{tab}">'
                   f'<span class="ti" aria-hidden="true">{icon}</span>'
                   f'{_e(title)}{badge_html}</button>')
        lead = _TAB_LEADS.get(tab, "")
        lead_html = f'<p class="lead">{_e(lead)}</p>' if lead else ""
        panels.append(f'<section class="panel{" active" if active else ""}" '
                      f'id="tab-{tab}" role="tabpanel" '
                      f'aria-labelledby="tabbtn-{tab}">'
                      f'<div class="panel-head"><h2>{icon} {_e(title)}</h2>'
                      f'{lead_html}</div>{_PANELS[tab](report)}</section>')
    title = f"Migration report — {report['title']}"
    footer = (f'<footer>S1 Command Center {_e(report["tool"]["version"])} · '
              f'Migration report v{REPORT_VERSION} · Generated '
              f'{_e(fmt_when(report["generatedAt"], True))} · '
              f'Made by Ran Jacobi</footer>')
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, '
            'initial-scale=1">'
            f"<title>{_e(title)}</title>{_THEME_BOOT}"
            f"<style>{_PAGE_CSS}</style></head><body>"
            f'<div class="wrap">{_hero(report)}<div id="nav-anchor"></div>'
            '<nav class="tabs" role="tablist" aria-label="Report sections">'
            + "".join(nav) + "</nav>" + "".join(panels) + footer
            + "</div>" + _REPORT_JS + _PAGE_JS + "</body></html>")
