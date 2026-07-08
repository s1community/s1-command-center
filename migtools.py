"""Migration support logic — pure, testable helpers used by the GUI pages.

Kept free of Tk/network so it can be unit-tested directly:
  * AuditLog            — append-only record of tool operations
  * evaluate_preflight  — turn gathered facts into pass/warn/fail checks
  * reconcile_agents    — did the agents actually move?
  * diff_config_fields  — value-level diff for settings/policy singletons
"""
import json
import os
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════
#  Audit history
# ═══════════════════════════════════════════════════════════════════════

class AuditLog:
    """Append-only JSONL log of what the tool did. One JSON object per line so
    it survives partial writes and is trivial to tail. Owner-only (0600)."""

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass

    def record(self, action, *, when, **fields):
        """Append one event. `when` is supplied by the caller (ISO string) so
        this module stays free of the forbidden clock calls."""
        entry = {"when": when, "action": action}
        entry.update(fields)
        line = json.dumps(entry, default=str)
        with open(self.path, "a") as f:
            f.write(line + "\n")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return entry

    def recent(self, limit=50):
        """Most-recent-first list of past events (best-effort; skips bad lines)."""
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        out.reverse()
        return out[:limit]


# ═══════════════════════════════════════════════════════════════════════
#  Pre-flight readiness
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Check:
    name: str
    status: str   # "pass" | "warn" | "fail" | "info"
    detail: str


def _days_until(expires_iso, now_iso):
    """Whole days between two ISO-8601 instants, or None if unparseable.
    Avoids datetime.now() (forbidden) — the caller passes `now_iso`."""
    from datetime import datetime
    if not expires_iso or not now_iso:
        return None
    try:
        def _p(s):
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s)
        return (_p(expires_iso) - _p(now_iso)).days
    except Exception:
        return None


def evaluate_preflight(facts: dict) -> list:
    """Turn gathered facts into an ordered list of Check results.

    facts keys (all optional — missing → 'info/unknown'):
      src_reachable, dst_reachable : bool
      token_expires, now           : ISO strings (destination token)
      token_scope                  : "account" | "site" | "global" | "tenant"
      target_type                  : "global" | "account" | "site" | "group"
      dest_scope_exists            : bool | None  (does the target acct/site exist)
      licenses_total, licenses_used: int | None
      agents_to_move               : int | None
    """
    checks = []

    # Reachability ────────────────────────────────────────────────────
    for key, label in (("src_reachable", "Source console"),
                        ("dst_reachable", "Destination console")):
        if key in facts:
            ok = bool(facts[key])
            checks.append(Check(
                f"{label} reachable",
                "pass" if ok else "fail",
                "responded to an authenticated request" if ok
                else "did not respond — check the connection/token"))

    # Token expiry ──────────────────────────────────────────────────────
    days = _days_until(facts.get("token_expires"), facts.get("now"))
    if facts.get("token_expires"):
        if days is None:
            checks.append(Check("Destination token expiry", "info",
                                f"expires {facts['token_expires']}"))
        elif days < 0:
            checks.append(Check("Destination token expiry", "fail",
                                f"token EXPIRED {-days} day(s) ago"))
        elif days <= 14:
            checks.append(Check("Destination token expiry", "warn",
                                f"token expires in {days} day(s)"))
        else:
            checks.append(Check("Destination token expiry", "pass",
                                f"valid for {days} more day(s)"))

    # Token scope vs target ─────────────────────────────────────────────
    scope = (facts.get("token_scope") or "").lower()
    target = (facts.get("target_type") or "").lower()
    if scope and target:
        rank = {"site": 1, "account": 2, "global": 3, "tenant": 3}
        need = {"group": 1, "site": 1, "account": 2, "global": 3}
        s, t = rank.get(scope, 0), need.get(target, 0)
        if s and t and s < t:
            checks.append(Check(
                "Token scope", "fail",
                f"token is scoped to '{scope}' but the migration targets "
                f"'{target}' — it likely can't write at that level"))
        else:
            checks.append(Check("Token scope", "pass",
                                f"'{scope}' scope covers a '{target}' target"))

    # Destination scope exists ──────────────────────────────────────────
    if facts.get("dest_scope_exists") is not None:
        if facts["dest_scope_exists"]:
            checks.append(Check("Destination scope", "pass",
                                "target account/site already exists"))
        else:
            checks.append(Check("Destination scope", "warn",
                                "target account/site not found — it will be "
                                "created during restore"))

    # License headroom ─────────────────────────────────────────────────
    total = facts.get("licenses_total")
    used = facts.get("licenses_used")
    need_n = facts.get("agents_to_move")
    if total is not None and used is not None:
        free = total - used
        if need_n:
            if free < need_n:
                checks.append(Check(
                    "License headroom", "fail",
                    f"{free} free license(s) but {need_n} agent(s) to move"))
            else:
                checks.append(Check("License headroom", "pass",
                                    f"{free} free license(s) for {need_n} agent(s)"))
        else:
            checks.append(Check(
                "License headroom",
                "warn" if free <= 0 else "pass",
                f"{free} free license(s) on destination"))

    if not checks:
        checks.append(Check("Pre-flight", "info",
                            "no facts were gathered to evaluate"))
    return checks


def preflight_verdict(checks: list) -> str:
    """Worst status across checks → overall verdict."""
    statuses = {c.status for c in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if "pass" in statuses:
        return "pass"
    return "info"


# ═══════════════════════════════════════════════════════════════════════
#  Agent-migration reconciliation
# ═══════════════════════════════════════════════════════════════════════

def reconcile_agents(expected_moved, src_before, src_after,
                     dst_before, dst_after):
    """Did the agents actually move? Returns a dict summary.

    expected_moved : how many we sent move commands for
    src_before/after, dst_before/after : agent counts on each side
    """
    src_drop = src_before - src_after
    dst_gain = dst_after - dst_before
    issues = []
    if expected_moved and src_drop < expected_moved:
        issues.append(
            f"{expected_moved - src_drop} agent(s) still report to the source")
    if dst_gain < src_drop:
        issues.append(
            f"{src_drop - dst_gain} agent(s) left the source but have not "
            f"appeared on the destination yet")
    return {
        "expected_moved": expected_moved,
        "source_drop": src_drop,
        "dest_gain": dst_gain,
        "reconciled": not issues,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Backup retention
# ═══════════════════════════════════════════════════════════════════════

def select_backups_to_prune(entries, keep_last=20, keep_days=0, now_ts=None):
    """Decide which backup files to delete under a retention policy.

    entries  : list of (path, mtime_epoch)
    keep_last: always keep this many newest files
    keep_days: also keep anything younger than this many days (0 = ignore age)
    now_ts   : current epoch seconds (passed in — module avoids the clock)

    Returns the list of paths to delete (oldest-first)."""
    ordered = sorted(entries, key=lambda e: e[1], reverse=True)  # newest first
    prune = []
    for i, (path, mtime) in enumerate(ordered):
        if i < keep_last:
            continue  # within the newest keep_last
        if keep_days and now_ts is not None:
            age_days = (now_ts - mtime) / 86400.0
            if age_days <= keep_days:
                continue  # young enough to keep
        prune.append(path)
    return prune


# ═══════════════════════════════════════════════════════════════════════
#  Backup integrity
# ═══════════════════════════════════════════════════════════════════════

def check_backup_integrity(nodes):
    """Sanity-check a loaded backup before it is used for a restore. Returns
    {ok, errors, warnings, node_count, element_nodes}. `errors` mean the file
    is unusable; `warnings` are worth surfacing but not fatal."""
    errors, warnings = [], []
    if not isinstance(nodes, list):
        return {"ok": False, "errors": ["backup is not a list of nodes"],
                "warnings": [], "node_count": 0, "element_nodes": 0}
    if not nodes:
        warnings.append("backup contains no nodes")
    has_meta = False
    element_nodes = 0
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errors.append(f"node {i} is not an object")
            continue
        if not n.get("type"):
            warnings.append(f"node {i} is missing its 'type'")
        if "data" not in n:
            warnings.append(
                f"node {i} ({n.get('path', '?')}) has no 'data' block")
        elif n.get("data"):
            element_nodes += 1
        if n.get("backupMetadata"):
            has_meta = True
    if nodes and not has_meta:
        warnings.append(
            "no backupMetadata found — source console / scope / timestamp "
            "are unknown")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "node_count": len(nodes), "element_nodes": element_nodes}


# ═══════════════════════════════════════════════════════════════════════
#  Field-level config / settings diff
# ═══════════════════════════════════════════════════════════════════════

# Volatile / non-portable keys that should never count as a "difference"
# (ids, timestamps, scope bindings differ across consoles by design).
_DIFF_IGNORE_PARTS = (
    "id", "createdat", "updatedat", "scope", "inheritedfrom", "accountid",
    "siteid", "groupid", "creator", "token", "secret", "password",
)


def _ignored(key):
    k = str(key).lower().replace("_", "")
    return any(p in k for p in _DIFF_IGNORE_PARTS)


def diff_config_fields(src: dict, dst: dict, prefix=""):
    """Recursive value-level diff of two config dicts. Returns a list of
    {field, src, dst} for fields that differ (ignoring volatile keys).
    Used to upgrade settings/policy validation from presence to value-level."""
    diffs = []
    src = src or {}
    dst = dst or {}
    keys = [k for k in (list(src.keys()) + [k for k in dst if k not in src])]
    for k in keys:
        if _ignored(k):
            continue
        field = f"{prefix}{k}"
        sv, dv = src.get(k), dst.get(k)
        if isinstance(sv, dict) or isinstance(dv, dict):
            diffs.extend(diff_config_fields(sv if isinstance(sv, dict) else {},
                                            dv if isinstance(dv, dict) else {},
                                            prefix=f"{field}."))
        elif isinstance(sv, list) and isinstance(dv, list):
            # Compare lists order-insensitively by their stringified members.
            if sorted(map(str, sv)) != sorted(map(str, dv)):
                diffs.append({"field": field, "src": sv, "dst": dv})
        elif sv != dv:
            diffs.append({"field": field, "src": sv, "dst": dv})
    return diffs
