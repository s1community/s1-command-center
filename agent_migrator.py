"""
Agent Migration — the structure-aware agent migration workflow.

Agents are moved so that each one lands in the destination group of the
same name, not in one flat site. Three steps:

  1. READ the DESTINATION — walk account → sites → groups and record every
     scope's registration token into a JSON file (`build_scope_map`).
  2. MATCH the SOURCE against it — walk the source's scopes and pair each
     one with its same-named destination scope, so the operator can see
     what was found and what wasn't before anything moves
     (`build_match_plan`). Nothing is sent.
  3. MIGRATE — send `move-to-console` per group with that group's own
     token, then read each agent back to report what actually happened
     (`run_live_migration`, `verify_migration`).

Step 3 streams events so the UI can show every machine as it goes, with
the console's own reason when one doesn't make it. A scheduled run takes
the same path, so an unattended migration is just as auditable.

Around that sit a migration status report (counts per console-migration
status, optional passphrases, decommissioned agents) and a scheduler that
fires the live run at a chosen date and time.

Everything above the UI classes is a plain function, so the mapping and
migration logic is testable without a display.
"""
import customtkinter as ctk
import hashlib
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox

import config
from app import (run_async, cli_log, _ConsoleProxy, UI_FONT,
                 MONO_FONT, CARD, CARD_ELEVATED, BORDER, ACCENT, ACCENT_HOVER,
                 BRAND, BRAND_HOVER, GREEN, GREEN_HOVER, WARN, WARN_HOVER,
                 NEUTRAL, NEUTRAL_HOVER, TEXT, TEXT_MUTED, TEXT_FAINT)
from export_utils import export_agent_report
from s1_api import S1API, S1APIError
from theme import RADIUS_MD, RADIUS_SM

# One move-to-console call carries at most this many agent ids.
MOVE_BATCH = 1000

# Agents read back per request when confirming a move. Smaller than
# MOVE_BATCH because these ids go in the query string, not a JSON body.
VERIFY_BATCH = 100

# Group listings are fetched one site at a time, so a 64-account tenant is
# hundreds of round trips. Fan them out — same worker count as
# S1API.get_many, which the rest of the app already runs against a console.
GROUP_WORKERS = 8

# Groups counted at the same time when matching. These are read-only
# GETs, so the pool can be wider than the mapping one.
COUNT_WORKERS = 12

# The four values S1 reports in `consoleMigrationStatus`.
MIGRATION_STATUSES = ["Migrated", "Pending", "N/A", "Failed"]

AGENT_REPORT_COLUMNS = [
    "Computer Name", "Migration Status", "Site", "Group", "OS",
    "Last User", "Decommissioned", "Passphrase", "UUID", "Agent ID",
]

_CONSOLE_RE = re.compile(r"(https://[^/\s]+\.sentinelone\.net)", re.I)


class MappingError(Exception):
    """A source scope has no same-named counterpart in the map file."""

    def __init__(self, kind: str, name: str, candidates=None):
        super().__init__(f"{kind} '{name}' is not in the map file")
        self.kind = kind
        self.name = name
        self.candidates = list(candidates or [])


def parse_console_url(value: str) -> str:
    """Reduce anything pasted from a browser to the console's base URL."""
    text = (value or "").strip()
    m = _CONSOLE_RE.search(text)
    return m.group(1) if m else text.rstrip("/")


def norm_name(value) -> str:
    """Scope names are matched case-insensitively, whitespace-collapsed."""
    return " ".join(str(value or "").casefold().split())


def batched(seq, size: int):
    """Yield `seq` in lists of at most `size` items."""
    items = list(seq)
    for i in range(0, len(items), max(1, size)):
        yield items[i:i + max(1, size)]


# ── step 1: map the destination ────────────────────────────────────────

def split_ids(value) -> list:
    """'100, 200 300\\n400' → ['100','200','300','400']."""
    return [p for p in re.split(r"[\s,;]+", str(value or "").strip()) if p]


def resolve_accounts(api, account_ids="") -> list:
    """The accounts to work on.

    Blank means EVERY account the token can see — the normal case on a
    multi-tenant console where you're migrating all 60-odd accounts, not
    one. Otherwise each id given is resolved, and any that can't be is
    named rather than silently dropped.
    """
    wanted = split_ids(account_ids)
    if not wanted:
        accounts = [dict(a) for a in api.get_accounts()]
        if not accounts:
            raise ValueError("This token cannot see any account.")
        return accounts
    found, missing = [], []
    for aid in wanted:
        acct = api.get_account_by_id(aid)
        if acct:
            found.append(dict(acct))
        else:
            missing.append(aid)
    if missing:
        raise ValueError(
            "Not found on this console (or not visible to the token): "
            + ", ".join(missing))
    return found


def _groups_for_sites(api, sites: list, workers: int = GROUP_WORKERS) -> list:
    """Each site as a map entry with its groups, input order preserved."""
    def one(site):
        srec = {"name": site.get("name", ""), "id": str(site.get("id", "")),
                "token": site.get("registrationToken") or "",
                "type": "site", "groups": []}
        for grp in api.get_groups(params={"siteIds": srec["id"]}):
            srec["groups"].append({
                "name": grp.get("name", ""), "id": str(grp.get("id", "")),
                "token": grp.get("registrationToken") or "", "type": "group"})
        return srec

    if len(sites) < 2 or workers < 2:
        return [one(s) for s in sites]
    with ThreadPoolExecutor(max_workers=min(workers, len(sites))) as ex:
        return list(ex.map(one, sites))


def build_scope_map(api, account_ids: str = "", site_id: str = "", log=None,
                    should_stop=None, workers: int = GROUP_WORKERS) -> list:
    """Destination accounts → sites → groups, each with its registration token.

    `account_ids` blank maps EVERY account the token can see; pass one id,
    or several separated by commas/spaces, to narrow it.

    Shape matches the standalone tool's JSON so existing map files still
    load: a list of account dicts, each with `sites`, each with `groups`.
    """
    say = log or (lambda _m: None)
    stop = should_stop or (lambda: False)
    accounts = resolve_accounts(api, account_ids)
    say(f"{len(accounts)} account(s) to map.")

    out = []
    for n, acct in enumerate(accounts, 1):
        if stop():
            say("Stopped — the map holds only the accounts walked so far.")
            break
        acct_id = str(acct.get("id", ""))
        entry = {"name": acct.get("name", ""), "id": acct_id,
                 "type": "account", "sites": []}
        params = {"accountId": acct_id}
        if split_ids(site_id):
            params["siteIds"] = ",".join(split_ids(site_id))
        sites = api.get_sites(params=params)
        entry["sites"] = _groups_for_sites(api, sites, workers)
        no_token = [s["name"] for s in entry["sites"] if not s["token"]]
        groups = sum(len(s["groups"]) for s in entry["sites"])
        say(f"[{n}/{len(accounts)}] {entry['name']}: {len(sites)} site(s), "
            f"{groups} group(s)"
            + (f"   ⚠ no registration token on: {', '.join(no_token)}"
               if no_token else ""))
        out.append(entry)
    return out


def map_counts(map_data) -> tuple:
    """(accounts, sites, groups) held in a map file."""
    accounts = len(map_data or [])
    sites = sum(len(a.get("sites") or []) for a in map_data or [])
    groups = sum(len(s.get("groups") or [])
                 for a in map_data or [] for s in a.get("sites") or [])
    return accounts, sites, groups


def find_by_name(items, name: str, kind: str) -> dict:
    """The entry in `items` whose name matches `name`, or MappingError."""
    needle = norm_name(name)
    for item in items or []:
        if norm_name(item.get("name")) == needle:
            return item
    raise MappingError(kind, name,
                       [str(i.get("name", "")) for i in items or []])


def token_for(group: dict, site: dict) -> str:
    """A group's own registration token, else its site's."""
    return (str(group.get("token") or "").strip()
            or str(site.get("token") or "").strip())


def rename_in_map(map_data, kind: str, old_name: str, new_name: str) -> bool:
    """Rename the first `kind` entry called `old_name`, in place.

    Name mismatches between the two consoles are the single most common
    reason a mapped migration skips a scope; renaming the map entry to the
    SOURCE's spelling is what makes the next run match it.
    """
    old = norm_name(old_name)
    for acct in map_data or []:
        if kind == "account":
            if norm_name(acct.get("name")) == old:
                acct["name"] = new_name
                return True
            continue
        for site in acct.get("sites") or []:
            if kind == "site":
                if norm_name(site.get("name")) == old:
                    site["name"] = new_name
                    return True
                continue
            for grp in site.get("groups") or []:
                if norm_name(grp.get("name")) == old:
                    grp["name"] = new_name
                    return True
    return False


# ── reading the source's agents ────────────────────────────────────────

def _still_to_move(rows) -> list:
    return [a for a in rows
            if str(a.get("consoleMigrationStatus") or "") != "Migrated"]


def agents_for_group(api, group_id: str, skip_migrated: bool = True) -> list:
    """The agent RECORDS in one group that still need moving.

    Records, not ids, because the live view names every machine it is
    moving — an operator watching a migration needs to see "WIN-SRV-01",
    not "f4c1a09b8e2d4f7a".

    `consoleMigrationStatusesNin` is accepted by the move-to-console
    action's filter, but not every console accepts it as a GET /agents
    query param — one that rejects it would otherwise fail the whole
    group. A 400/422 falls back to filtering the rows we got back.
    """
    base = {"groupIds": str(group_id)}
    if not skip_migrated:
        return list(api.get_agents(params=base))
    try:
        rows = api.get_agents(
            params=dict(base, consoleMigrationStatusesNin="Migrated"))
    except S1APIError as e:
        if e.status_code not in (400, 422):
            raise
        rows = api.get_agents(params=base)
    return _still_to_move(rows)


def agent_ids_for_group(api, group_id: str, skip_migrated: bool = True) -> list:
    """Just the ids, for the counting pass."""
    return [str(a.get("id"))
            for a in agents_for_group(api, group_id, skip_migrated)
            if a.get("id")]


def _unmatched(err: MappingError, path: str) -> dict:
    return {"kind": err.kind, "name": err.name, "path": path,
            "candidates": err.candidates}


# ── step 2: pair every source scope with its destination ───────────────
#
# Nothing moves here. The operator gets one row per source group saying
# exactly which destination scope it will land in and how many agents go
# with it — the old build only ever showed totals, so "did it find my
# scopes?" could not be answered until after the run.

PLAN_COLUMNS = ["Account", "Site", "Group", "Destination", "Agents", "Status"]

NO_MATCH_ACCOUNT = "account not on destination"
NO_MATCH_SITE = "site not on destination"
NO_MATCH_GROUP = "group not on destination"
NO_TOKEN = "no registration token"
ALL_DONE = "already migrated"
UNREADABLE = "cannot read agents"


def _plan_row(account, site, group, **kw) -> dict:
    row = {"Account": account, "Site": site, "Group": group,
           "Destination": "—", "Agents": 0, "Total": 0, "Status": "",
           "state": "blocked", "reason": "", "kind": "", "group_id": "",
           "token": "", "token_from": "", "counted": False,
           "dest_account": "", "dest_site": "", "dest_group": ""}
    row.update(kw)
    row["key"] = f"{row['Account']}\x1f{row['Site']}\x1f{row['Group']}"
    return row


def retally(plan: dict) -> dict:
    """Recount the headline numbers from the rows, in place."""
    plan["ready"] = plan["blocked"] = plan["done"] = plan["agents"] = 0
    for row in plan.get("rows") or []:
        if row["state"] == "ready":
            plan["ready"] += 1
            plan["agents"] += row["Agents"]
        elif row["state"] == "done":
            plan["done"] += 1
        else:
            plan["blocked"] += 1
    return plan


def _source_groups(api, sites: list, workers: int = GROUP_WORKERS) -> list:
    """Each site's source groups, in the order the sites were given."""
    def one(site):
        return api.get_groups(params={"siteIds": str(site.get("id", ""))})

    if len(sites) < 2 or workers < 2:
        return [one(s) for s in sites]
    with ThreadPoolExecutor(max_workers=min(workers, len(sites))) as ex:
        return list(ex.map(one, sites))


def _plan_one_account(api, acct, map_data, site_id, plan, say, stop, on_row,
                      workers=GROUP_WORKERS) -> None:
    """Pair one source account's scopes into `plan` (mutated in place)."""
    acct_name = acct.get("name", "")

    def add(row):
        plan["rows"].append(row)
        if row["state"] == "ready":
            plan["ready"] += 1
            plan["agents"] += row["Agents"]
        elif row["state"] == "done":
            plan["done"] += 1
        else:
            plan["blocked"] += 1
        if on_row:
            on_row(row)

    try:
        m_acct = find_by_name(map_data, acct_name, "account")
    except MappingError as e:
        plan["unmatched"].append(_unmatched(e, acct_name))
        say(f"  ✗ account '{acct_name}' is not on the destination")
        add(_plan_row(acct_name, "—", "—", Status=NO_MATCH_ACCOUNT,
                      kind="account",
                      reason=f"The destination has no account named "
                             f"'{acct_name}', so nothing under it can "
                             f"move."))
        return

    params = {"accountId": str(acct.get("id", ""))}
    if split_ids(site_id):
        params["siteIds"] = ",".join(split_ids(site_id))
    sites = api.get_sites(params=params)
    say(f"  {acct_name}: {len(sites)} source site(s)")
    groups_by_site = _source_groups(api, sites, workers)

    for site, site_groups in zip(sites, groups_by_site):
        if stop():
            plan["stopped"] = True
            return
        sname = site.get("name", "")
        try:
            m_site = find_by_name(m_acct.get("sites"), sname, "site")
        except MappingError as e:
            plan["unmatched"].append(_unmatched(e, acct_name))
            say(f"    ✗ site '{sname}' is not on the destination")
            add(_plan_row(acct_name, sname, "—", Status=NO_MATCH_SITE,
                          kind="site",
                          reason=f"Account '{acct_name}' on the destination "
                                 f"has no site named '{sname}'."))
            continue

        for grp in site_groups:
            if stop():
                plan["stopped"] = True
                return
            gname = grp.get("name", "")
            total = int(grp.get("totalAgents") or 0)
            if total == 0:
                plan["empty_groups"] += 1
                continue
            try:
                m_grp = find_by_name(m_site.get("groups"), gname, "group")
            except MappingError as e:
                plan["unmatched"].append(
                    _unmatched(e, f"{acct_name} / {sname}"))
                say(f"    ✗ group '{gname}' is not on the destination")
                add(_plan_row(acct_name, sname, gname, Total=total,
                              Status=NO_MATCH_GROUP, kind="group",
                              reason=f"Site '{sname}' on the destination has "
                                     f"no group named '{gname}' — its "
                                     f"{total} agent(s) stay put."))
                continue

            token = token_for(m_grp, m_site)
            dest = (f"{m_acct.get('name', '')} / {m_site.get('name', '')} / "
                    f"{m_grp.get('name', '')}")
            common = dict(Destination=dest, Total=total,
                          group_id=str(grp.get("id", "")), token=token,
                          dest_account=m_acct.get("name", ""),
                          dest_site=m_site.get("name", ""),
                          dest_group=m_grp.get("name", ""))
            if not token:
                add(_plan_row(acct_name, sname, gname, Status=NO_TOKEN,
                              reason=f"Neither the destination group "
                                     f"'{gname}' nor its site '{sname}' has "
                                     f"a registration token. Create one on "
                                     f"the destination console.", **common))
                continue

            from_where = "group" if str(m_grp.get("token") or "").strip() \
                else "site"
            # The group listing's own total, so the pairing shows up at
            # once; refine_plan_counts corrects it to what still needs
            # moving. One GET per group is what used to make this slow.
            add(_plan_row(acct_name, sname, gname, state="ready",
                          Agents=total,
                          Status=f"ready · {from_where} token",
                          token_from=from_where, **common))


def refine_plan_counts(api, plan: dict, on_row=None, should_stop=None,
                       workers: int = COUNT_WORKERS) -> dict:
    """Correct every ready row's count to what still needs moving.

    The pairing pass uses the group listing's own total so the operator
    sees the whole plan at once. That total counts agents that already
    migrated, so each ready group is read once here to get the real
    number — in parallel, because one blocking GET per group is what
    made this step a coffee break on a 64-account console.
    """
    stop = should_stop or (lambda: False)
    rows = [r for r in plan.get("rows") or [] if r["state"] == "ready"]
    if not rows:
        plan["counted"] = True
        return plan

    def one(row):
        if stop():
            return row, None, None
        try:
            return row, len(agent_ids_for_group(api, row["group_id"])), None
        except Exception as e:
            return row, None, e

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(rows)))) as ex:
        for row, eligible, err in ex.map(one, rows):
            if err is not None:
                row.update(state="blocked", Status=UNREADABLE, reason=str(err))
            elif eligible is None:
                plan["stopped"] = True
                continue
            elif eligible == 0:
                row.update(state="done", Status=ALL_DONE, Agents=0,
                           reason=f"All {row['Total']} agent(s) have already "
                                  f"migrated.")
            else:
                row["Agents"] = eligible
            row["counted"] = True
            if on_row:
                on_row(row)

    retally(plan)
    plan["counted"] = True
    return plan


def build_match_plan(api, map_data, account_ids: str = "", site_id: str = "",
                     log=None, should_stop=None, on_row=None,
                     count_agents: bool = True,
                     workers: int = GROUP_WORKERS) -> dict:
    """Every source scope paired with the destination scope it maps to.

    Nothing is sent. Two passes, so the operator is never left staring at
    a spinner: the first pairs every scope and reports the group's own
    agent total, which is enough to answer "did it find my scopes and
    where is each one going?"; the second (`refine_plan_counts`) corrects
    those totals to what still needs moving.

    `on_row` fires for each row in both passes — the same row object, so
    a UI keyed on `row["key"]` updates in place rather than duplicating.
    """
    say = log or (lambda _m: None)
    stop = should_stop or (lambda: False)
    plan = {"rows": [], "unmatched": [], "accounts": 0, "ready": 0,
            "blocked": 0, "done": 0, "agents": 0, "empty_groups": 0,
            "stopped": False, "counted": False}

    accounts = resolve_accounts(api, account_ids)
    say(f"Reading {len(accounts)} source account(s).")
    for n, acct in enumerate(accounts, 1):
        if stop():
            plan["stopped"] = True
            break
        say(f"[{n}/{len(accounts)}] {acct.get('name', '')}")
        plan["accounts"] += 1
        _plan_one_account(api, acct, map_data, site_id, plan, say, stop,
                          on_row, workers)

    if count_agents and not plan["stopped"]:
        say(f"Counting agents in {plan['ready']} matched group(s)…")
        refine_plan_counts(api, plan, on_row, stop)
    return plan


# ── remembering the plan between sessions ──────────────────────────────
#
# Matching a 64-account console costs hundreds of round trips. The result
# only changes when the consoles or the map do, so it is cached against a
# fingerprint of exactly those inputs and restored on the next launch —
# step 3 is then usable straight away, with the plan's age on screen so a
# stale one is a visible choice rather than an accident.

PLAN_CACHE_NAME = "agent_match_plan.json"


def plan_cache_path() -> str:
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    return os.path.join(config.CONFIG_DIR, PLAN_CACHE_NAME)


def plan_fingerprint(source_url: str, account_ids: str, site_id: str,
                     map_path: str, map_data) -> dict:
    """What the plan depended on. Any change invalidates the cache."""
    blob = json.dumps(map_data or [], sort_keys=True, default=str)
    return {
        "source": str(source_url or ""),
        "accounts": " ".join(split_ids(account_ids)),
        "site": " ".join(split_ids(site_id)),
        "map_path": str(map_path or ""),
        "map_hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
    }


def save_plan(plan: dict, fingerprint: dict, path: str = "") -> str:
    """Cache a plan. Registration tokens are deliberately NOT written —
    they live in the map file, and are restored from it on load."""
    rows = []
    for row in plan.get("rows") or []:
        clean = {k: v for k, v in row.items() if k != "token"}
        rows.append(clean)
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds"),
               "fingerprint": fingerprint,
               "plan": dict(plan, rows=rows)}
    target = path or plan_cache_path()
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return target


def load_plan(fingerprint: dict, map_data, path: str = "") -> tuple:
    """(plan, saved_at) for a cached plan that still matches, else (None, "").

    The tokens stripped by `save_plan` are re-read from the CURRENT map,
    so a rotated token is picked up and a scope that has since vanished
    from the map turns back into a blocked row instead of a bad move.
    """
    target = path or plan_cache_path()
    try:
        with open(target, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None, ""
    if payload.get("fingerprint") != fingerprint:
        return None, ""
    plan = payload.get("plan") or {}
    if not isinstance(plan.get("rows"), list):
        return None, ""
    for row in plan["rows"]:
        row.setdefault("token", "")
    rehydrate_tokens(plan, map_data)
    return plan, str(payload.get("saved_at") or "")


def rehydrate_tokens(plan: dict, map_data) -> dict:
    """Re-resolve each ready row's destination token from the map."""
    for row in plan.get("rows") or []:
        if row.get("state") != "ready":
            continue
        try:
            acct = find_by_name(map_data, row["dest_account"], "account")
            site = find_by_name(acct.get("sites"), row["dest_site"], "site")
            grp = find_by_name(site.get("groups"), row["dest_group"], "group")
        except MappingError:
            row.update(state="blocked", Status=NO_MATCH_GROUP, token="",
                       reason=f"'{row['dest_group']}' is no longer in the "
                              f"map file. Read the destination again.")
            continue
        token = token_for(grp, site)
        row["token"] = token
        if not token:
            row.update(state="blocked", Status=NO_TOKEN,
                       reason=f"The destination scope no longer has a "
                              f"registration token. Create one, then read "
                              f"the destination again.")
    return retally(plan)


def forget_plan(path: str = "") -> None:
    try:
        os.remove(path or plan_cache_path())
    except OSError:
        pass


def plan_age(saved_at: str) -> str:
    """'4 minutes ago' for a cached plan's timestamp."""
    try:
        when = datetime.fromisoformat(saved_at)
    except (TypeError, ValueError):
        return "earlier"
    secs = max(0, int((datetime.now() - when).total_seconds()))
    if secs < 90:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def plan_blockers(plan: dict) -> dict:
    """Blocked rows grouped by what is wrong, for the summary line."""
    out = {}
    for row in plan.get("rows") or []:
        if row["state"] == "blocked":
            out.setdefault(row["Status"], []).append(row)
    return out


# ── step 3: move them, and watch each one ──────────────────────────────

LIVE_COLUMNS = ["Computer", "OS", "Group", "Destination", "Result", "Detail"]

# consoleMigrationStatus → (what to show, why)
_SETTLED = {
    "Migrated": ("moved", "Confirmed on the destination console."),
    "Pending": ("pending", "Accepted — the agent moves when it next "
                           "checks in."),
    "Failed": ("failed", "The console reports the migration as failed. "
                         "Check the agent is online and the destination "
                         "token is still valid."),
    "N/A": ("pending", "The console has not picked the request up yet."),
}
_ACCEPTED = "Accepted by the console — not confirmed on the agent yet."


def mask_token(token: str) -> str:
    """Registration tokens are secrets and the live log is screenshotted,
    so only ever show enough to tell two tokens apart."""
    text = str(token or "")
    return f"…{text[-6:]}" if len(text) > 6 else ("…" if text else "(none)")


def verify_migration(api, agent_ids) -> dict:
    """agent id → the console's current consoleMigrationStatus.

    The bulk endpoint answers with a count, not per-agent results, so this
    read-back is the only way to tell "the console accepted 400 agents"
    from "400 agents actually moved".
    """
    out = {}
    for chunk in batched([str(a) for a in agent_ids], VERIFY_BATCH):
        try:
            rows = api.get_agents(params={"ids": ",".join(chunk)})
        except Exception:
            continue                      # a failed read-back is not a
        for a in rows:                    # failed migration
            out[str(a.get("id"))] = str(a.get("consoleMigrationStatus") or "")
    return out


def where_of(row: dict) -> str:
    return f"{row['Account']} / {row['Site']} / {row['Group']}"


def _live_record(agent: dict, row: dict) -> dict:
    aid = str(agent.get("id", ""))
    return {"id": aid,
            "Computer": agent.get("computerName", "") or aid,
            "OS": agent.get("osName", ""),
            "Account": row["Account"], "Site": row["Site"],
            "Group": row["Group"], "Destination": row["Destination"],
            "Result": "queued", "Detail": "", "Agent ID": aid,
            "offline": agent.get("isActive") is False}


def _settle_batch(api, records, batch, run, emit, verify) -> None:
    """Turn "the console accepted N" into a per-agent answer."""
    statuses = verify_migration(api, batch) if verify else {}
    for aid in batch:
        rec = records[aid]
        state, detail = _SETTLED.get(statuses.get(aid, ""),
                                     ("pending", _ACCEPTED))
        if state == "pending" and rec.get("offline"):
            detail = ("Accepted — this agent is offline, so it moves the "
                      "next time it connects.")
        rec["Result"], rec["Detail"] = state, detail
        run[state] += 1
        emit({"type": "agent", "rec": dict(rec)})


def run_live_migration(api, rows, on_event=None, should_stop=None,
                       skip_migrated: bool = True,
                       verify: bool = True) -> dict:
    """Move every ready row of a match plan, reporting each agent as it goes.

    `on_event` receives dicts describing the run as it happens — the group
    being worked, the request going out, and each agent's outcome. That is
    what the step-3 panel draws; pass None for an unattended run.
    """
    emit = on_event or (lambda _e: None)
    stop = should_stop or (lambda: False)
    ready = [r for r in rows if r.get("state") == "ready"]
    run = {"agents": [], "errors": [], "by_group": [], "groups": 0,
           "sent": 0, "affected": 0, "moved": 0, "pending": 0, "failed": 0,
           "stopped": False, "verified": bool(verify)}
    emit({"type": "start", "groups": len(ready),
          "agents": sum(int(r.get("Agents") or 0) for r in ready)})

    for index, row in enumerate(ready, 1):
        if stop():
            run["stopped"] = True
            break
        emit({"type": "group", "index": index, "total": len(ready),
              "row": row})
        try:
            agents = agents_for_group(api, row["group_id"], skip_migrated)
        except Exception as e:
            run["errors"].append(f"{where_of(row)}: {e}")
            emit({"type": "error", "where": where_of(row), "error": str(e)})
            continue

        run["groups"] += 1
        records = {}
        for agent in agents:
            rec = _live_record(agent, row)
            if rec["id"]:
                records[rec["id"]] = rec
                run["agents"].append(rec)
        # Copies: the consumer is on another thread and must see each
        # record as it was when the event fired, not as it ends up.
        emit({"type": "roster", "row": row,
              "recs": [dict(r) for r in records.values()]})

        tally = {"row": row, "candidates": len(records), "moved": 0,
                 "errors": []}
        chunks = list(batched(list(records), MOVE_BATCH))
        for n, batch in enumerate(chunks, 1):
            if stop():
                run["stopped"] = True
                break
            extra = {"groupIds": [str(row["group_id"])]}
            if skip_migrated:
                extra["consoleMigrationStatusesNin"] = ["Migrated"]
            for aid in batch:
                records[aid]["Result"] = "sending"
                emit({"type": "agent", "rec": dict(records[aid])})
            emit({"type": "request", "batch": n, "of": len(chunks),
                  "count": len(batch), "row": row,
                  "endpoint": "/agents/actions/move-to-console",
                  "token": mask_token(row["token"]), "filter": extra})
            try:
                res = api.move_agents_to_console(batch, row["token"], extra)
                affected = int(((res or {}).get("data") or {})
                               .get("affected") or 0)
            except Exception as e:
                detail = str(e)
                run["errors"].append(f"{where_of(row)}: {detail}")
                tally["errors"].append(detail)
                for aid in batch:
                    rec = records[aid]
                    rec["Result"], rec["Detail"] = "failed", detail
                    run["failed"] += 1
                    emit({"type": "agent", "rec": dict(rec)})
                emit({"type": "response", "ok": False, "batch": n,
                      "error": detail})
                continue
            run["sent"] += len(batch)
            run["affected"] += affected
            tally["moved"] += affected
            emit({"type": "response", "ok": True, "batch": n,
                  "affected": affected, "of": len(batch)})
            _settle_batch(api, records, batch, run, emit, verify)

        run["by_group"].append(tally)
        emit({"type": "group_done", "tally": tally})

    emit({"type": "done", "run": run})
    return run


# ── migration status report ────────────────────────────────────────────

def _agent_row(api, agent: dict, status: str,
               fetch_passphrases: bool = False) -> dict:
    row = {
        "Computer Name": agent.get("computerName", ""),
        "Migration Status": status,
        "Site": agent.get("siteName", ""),
        "Group": agent.get("groupName", ""),
        "OS": agent.get("osName", ""),
        "Last User": agent.get("lastLoggedInUserName", ""),
        "Decommissioned": "Yes" if agent.get("isDecommissioned") else "No",
        "Passphrase": "not fetched",
        "UUID": agent.get("uuid", ""),
        "Agent ID": str(agent.get("id", "")),
    }
    if fetch_passphrases and row["Agent ID"]:
        try:
            data = api.get_agent_passphrase(row["Agent ID"]) or []
            row["Passphrase"] = (data[0].get("passphrase", "")
                                 if data else "unavailable")
        except Exception as e:
            row["Passphrase"] = f"error: {e}"
    return row


def count_agents_by_status(api, account_ids: str = "", site_id: str = "",
                           fetch_passphrases: bool = False, log=None,
                           should_stop=None) -> dict:
    """Agents per console-migration status, plus decommissioned agents.

    `account_ids` may name several accounts (comma/space separated); blank
    with no site means every agent the token can see.
    """
    say = log or (lambda _m: None)
    stop = should_stop or (lambda: False)
    sites = split_ids(site_id)
    if sites:
        scope = {"siteIds": ",".join(sites)}
    else:
        ids = split_ids(account_ids)
        scope = {"accountIds": ",".join(ids)} if ids else {}

    counts = {s: 0 for s in MIGRATION_STATUSES}
    rows, decommissioned = [], []
    for status in MIGRATION_STATUSES:
        if stop():
            break
        params = dict(scope)
        params["consoleMigrationStatuses"] = status
        agents = api.get_agents(params=params)
        counts[status] = len(agents)
        say(f"{status}: {len(agents)} agent(s)")
        for agent in agents:
            rows.append(_agent_row(api, agent, status, fetch_passphrases))

    if not stop():
        params = dict(scope)
        params["isDecommissioned"] = "true"
        try:
            for agent in api.get_agents(params=params):
                decommissioned.append(
                    _agent_row(api, agent, "Decommissioned",
                               fetch_passphrases))
            say(f"Decommissioned: {len(decommissioned)} agent(s)")
        except Exception as e:
            say(f"Could not list decommissioned agents: {e}")

    return {"counts": counts, "agents": rows,
            "decommissioned": decommissioned}


# ── scheduling ─────────────────────────────────────────────────────────

def parse_schedule(date_str: str, time_str: str, now=None) -> datetime:
    """'YYYY-MM-DD' + 'HH:MM' → a datetime that is in the future."""
    text = f"{(date_str or '').strip()} {(time_str or '').strip()}"
    try:
        when = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Use date YYYY-MM-DD and time HH:MM (24-hour).")
    if when <= (now or datetime.now()):
        raise ValueError("That moment has already passed — pick a future "
                         "date and time.")
    return when


def format_countdown(delta: timedelta) -> str:
    total = int(max(0, delta.total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    days, hours = divmod(hours, 24)
    head = f"{days}d " if days else ""
    return f"{head}{hours:02d}:{minutes:02d}:{seconds:02d}"


def sites_without_token(map_data) -> list:
    """Sites nothing can be migrated into: no site token, and at least one
    group under them with no token of its own either.

    Worth surfacing before a run rather than as a per-group error during
    one — it's a destination-console fix, not something to retry.
    """
    stranded = []
    for acct in map_data or []:
        for site in acct.get("sites") or []:
            if site.get("token"):
                continue
            groups = site.get("groups") or []
            if not groups or any(not g.get("token") for g in groups):
                stranded.append((acct.get("name", ""), site.get("name", "")))
    return stranded


def plan_summary_text(plan: dict) -> str:
    """Plain-English outcome of one match pass."""
    if not plan:
        return "No match yet."
    lines = ["SOURCE → DESTINATION MATCH — nothing has moved.", "",
             f"Accounts read:      {plan.get('accounts', 0)}",
             f"Groups matched:     {plan.get('ready', 0)}",
             f"Agents to migrate:  {plan.get('agents', 0)}",
             f"Cannot migrate:     {plan.get('blocked', 0)}",
             f"Already migrated:   {plan.get('done', 0)}",
             f"Empty groups:       {plan.get('empty_groups', 0)}"]
    if plan.get("stopped"):
        lines.append("Stopped early by the operator.")
    blocked = [r for r in plan.get("rows") or [] if r["state"] == "blocked"]
    if blocked:
        lines += ["", f"Will not migrate ({len(blocked)}):"]
        for row in blocked[:40]:
            lines.append(f"  • {where_of(row)} — {row['Status']}: "
                         f"{row['reason']}")
        if len(blocked) > 40:
            lines.append(f"  … and {len(blocked) - 40} more")
    return "\n".join(lines)


def live_summary_text(run: dict) -> str:
    """Plain-English outcome of one live migration, per agent."""
    if not run:
        return "No migration yet."
    lines = ["LIVE MIGRATION", "",
             f"Groups sent:        {run.get('groups', 0)}",
             f"Agents sent:        {run.get('sent', 0)}",
             f"Accepted by console:{run.get('affected', 0):>4}",
             f"Confirmed moved:    {run.get('moved', 0)}",
             f"Pending check-in:   {run.get('pending', 0)}",
             f"Failed:             {run.get('failed', 0)}"]
    if not run.get("verified"):
        lines.append("Per-agent confirmation was off, so 'moved' is what "
                     "the console accepted, not what arrived.")
    if run.get("stopped"):
        lines.append("Stopped early by the operator.")

    failures = [a for a in run.get("agents") or []
                if a.get("Result") == "failed"]
    if failures:
        lines += ["", f"Did not migrate ({len(failures)}):"]
        for agent in failures[:40]:
            lines.append(f"  • {agent['Computer']} "
                         f"({agent['Account']} / {agent['Site']} / "
                         f"{agent['Group']}): {agent['Detail']}")
        if len(failures) > 40:
            lines.append(f"  … and {len(failures) - 40} more")
    errors = run.get("errors") or []
    if errors:
        lines += ["", f"Errors ({len(errors)}):"]
        for err in errors[:20]:
            lines.append(f"  • {err}")
    return "\n".join(lines)


def status_summary_text(result: dict) -> str:
    """Plain-English outcome of one migration status report."""
    if not result:
        return "No report yet."
    counts = result.get("counts") or {}
    width = max([len(s) for s in MIGRATION_STATUSES] + [14])
    lines = ["Agents by console-migration status", ""]
    for status in MIGRATION_STATUSES:
        lines.append(f"  {status.ljust(width)}  {counts.get(status, 0)}")
    lines.append(f"  {'Decommissioned'.ljust(width)}  "
                 f"{len(result.get('decommissioned') or [])}")
    lines += ["", f"Total listed: {sum(counts.values())} agent(s)"]
    if any(r.get("Passphrase") not in ("", "not fetched")
           for r in result.get("agents") or []):
        lines += ["", "Passphrases are included in the export — treat that "
                      "file as sensitive."]
    return "\n".join(lines)


# ── rich report builders ───────────────────────────────────────────────
#
# Each export turns its result into the structured dict that
# export_utils.export_agent_report renders as a polished HTML document (or
# Excel / CSV / JSON). These are plain functions on plain dicts, so the
# report can be built and asserted without a console or a window.

def _stat(label, value, cls: str = "") -> dict:
    return {"label": label, "value": value, "class": cls}


def build_live_report(run: dict, source: str = "", map_path: str = "") -> dict:
    """Structured report for one live migration run."""
    run = run or {}
    agents = run.get("agents") or []
    moved, pending = run.get("moved", 0), run.get("pending", 0)
    failed = run.get("failed", 0)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    failures = [a for a in agents if a.get("Result") == "failed"]
    err_rows = [{"Error": e} for e in (run.get("errors") or [])]
    group_rows = [{
        "Group": where_of(t["row"]),
        "Destination": t["row"].get("Destination", ""),
        "Candidates": t.get("candidates", 0),
        "Accepted by console": t.get("moved", 0),
        "Errors": len(t.get("errors") or []),
    } for t in (run.get("by_group") or [])]

    sections = []
    if failures:
        sections.append({
            "title": "Did not migrate — manual action required",
            "icon": "✕", "color": "#ff6b81",
            "columns": ["Computer", "OS", "Group", "Destination", "Detail"],
            "rows": failures})
    if err_rows:
        sections.append({
            "title": "Errors", "icon": "⚠", "color": "#fdcb6e",
            "columns": ["Error"], "rows": err_rows})
    if group_rows:
        sections.append({
            "title": "Per group", "icon": "▦", "color": "#74b9ff",
            "columns": ["Group", "Destination", "Candidates",
                        "Accepted by console", "Errors"], "rows": group_rows})
    sections.append({
        "title": "Every agent", "icon": "🖥", "color": "#ffffff",
        "columns": LIVE_COLUMNS + ["Agent ID"], "rows": agents,
        "badge_cols": ["Result"], "empty": "No agents were processed."})

    note = None
    if run.get("stopped"):
        note = {"kind": "warn",
                "text": "The run was stopped early, so this report is partial."}
    elif not run.get("verified") and (moved or pending):
        note = {"kind": "info",
                "text": "Per-agent confirmation was off, so “moved” is what "
                        "the console accepted, not what was verified on each "
                        "agent. Run the Status report to confirm they arrived."}

    return {
        "title": "Agent Migration — Live Run", "icon": "🚚",
        "subtitle": "S1 Command Center — agents moved to the destination "
                    "console",
        "meta_line": f"Generated {now} • {len(agents)} agent(s) • "
                     f"{moved} moved • {pending} pending • "
                     f"{failed} failed",
        "info": [
            ("Source console", source or "—"),
            ("Destination map file", map_path or "—"),
            ("Groups migrated", run.get("groups", 0)),
            ("Agents sent", run.get("sent", 0)),
            ("Accepted by the console", run.get("affected", 0)),
            ("Per-agent confirmation", "on" if run.get("verified") else "off"),
        ],
        "stats": [
            _stat("Moved", moved),
            _stat("Pending check-in", pending, "warn"),
            _stat("Failed", failed, "accent" if failed else "muted"),
            _stat("Groups", run.get("groups", 0), "blue"),
            _stat("Accepted", run.get("affected", 0), "blue"),
        ],
        "note": note, "sections": sections,
        "flat": {"columns": LIVE_COLUMNS + ["Agent ID"], "rows": agents},
    }


def build_status_report(result: dict, console: str = "", scope: str = "",
                        passphrases: bool = False) -> dict:
    """Structured report for one migration status run."""
    result = result or {}
    counts = result.get("counts") or {}
    agents = list(result.get("agents") or [])
    decommissioned = list(result.get("decommissioned") or [])
    all_rows = agents + decommissioned
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    has_pass = any(r.get("Passphrase") not in ("", "not fetched", None)
                   for r in all_rows)
    note = None
    if has_pass:
        note = {"kind": "danger",
                "text": "This report contains agent passphrases — treat the "
                        "file as sensitive, store it securely and delete it "
                        "when finished. Each passphrase was recorded in the "
                        "source console's activity log when it was fetched."}

    return {
        "title": "Agent Migration — Status Report", "icon": "📋",
        "subtitle": "S1 Command Center — agents by console-migration status",
        "meta_line": f"Generated {now} • {len(all_rows)} agent(s)",
        "info": [
            ("Console", console or "—"),
            ("Scope", scope or "whole console"),
            ("Passphrases included", "yes" if has_pass else "no"),
        ],
        "stats": [
            _stat("Migrated", counts.get("Migrated", 0)),
            _stat("Pending", counts.get("Pending", 0), "warn"),
            _stat("Failed", counts.get("Failed", 0),
                  "accent" if counts.get("Failed") else "muted"),
            _stat("N/A", counts.get("N/A", 0), "muted"),
            _stat("Decommissioned", len(decommissioned), "muted"),
        ],
        "note": note,
        "sections": [{
            "title": "Agents", "icon": "🖥", "color": "#ffffff",
            "columns": AGENT_REPORT_COLUMNS, "rows": all_rows,
            "badge_cols": ["Migration Status"],
            "empty": "No agents in that scope."}],
        "flat": {"columns": AGENT_REPORT_COLUMNS, "rows": all_rows},
    }


def build_match_report(plan: dict, map_path: str = "") -> dict:
    """Structured report for one source→destination match pass."""
    plan = plan or {}
    rows = plan.get("rows") or []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _plain(rs):
        return [{k: r.get(k, "") for k in PLAN_COLUMNS} for r in rs]

    def _with_reason(rs):
        return [{**{k: r.get(k, "") for k in PLAN_COLUMNS},
                 "Reason": r.get("reason", "")} for r in rs]

    ready = [r for r in rows if r.get("state") == "ready"]
    blocked = [r for r in rows if r.get("state") == "blocked"]
    done = [r for r in rows if r.get("state") == "done"]

    sections = [
        {"title": "Will migrate", "icon": "✓", "color": "#00e0a4",
         "columns": PLAN_COLUMNS, "rows": _plain(ready),
         "empty": "No group is ready to migrate."},
        {"title": "Will not migrate", "icon": "✕", "color": "#ff6b81",
         "columns": PLAN_COLUMNS + ["Reason"], "rows": _with_reason(blocked),
         "empty": "Nothing is blocked."},
    ]
    if done:
        sections.append(
            {"title": "Already migrated", "icon": "≡", "color": "#74b9ff",
             "columns": PLAN_COLUMNS, "rows": _plain(done)})

    return {
        "title": "Agent Migration — Match Plan", "icon": "🧭",
        "subtitle": "S1 Command Center — source scopes matched to the "
                    "destination (nothing has moved)",
        "meta_line": f"Generated {now} • {len(rows)} scope(s)",
        "info": [
            ("Destination map file", map_path or "—"),
            ("Accounts read", plan.get("accounts", 0)),
            ("Agents to migrate", plan.get("agents", 0)),
        ],
        "stats": [
            _stat("Ready", plan.get("ready", 0)),
            _stat("Agents to migrate", plan.get("agents", 0), "blue"),
            _stat("Blocked", plan.get("blocked", 0),
                  "accent" if plan.get("blocked") else "muted"),
            _stat("Already migrated", plan.get("done", 0), "muted"),
            _stat("Empty groups", plan.get("empty_groups", 0), "muted"),
        ],
        "sections": sections,
        "flat": {"columns": PLAN_COLUMNS + ["State", "Reason"],
                 "rows": [{**{k: r.get(k, "") for k in PLAN_COLUMNS},
                           "State": r.get("state", ""),
                           "Reason": r.get("reason", "")} for r in rows]},
    }


# ═══════════════════════════════════════════════════════════════════════
#  Console picker — reuse the app's connections, or enter one by hand
# ═══════════════════════════════════════════════════════════════════════

class _ConnPicker(ctk.CTkFrame):
    """Pick which console a tab talks to: the app's connected SOURCE or
    DESTINATION, or a one-off URL + token typed in here."""

    ROLES = ("SOURCE", "DESTINATION", "Manual")

    def __init__(self, master, app, default: str = "SOURCE", **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.app = app
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Console:", font=(UI_FONT, 13)).grid(
            row=0, column=0, padx=(0, 8), pady=(2, 4), sticky="w")
        self._role = ctk.CTkSegmentedButton(
            self, values=list(self.ROLES), command=self._on_role,
            selected_color=BRAND, selected_hover_color=BRAND_HOVER)
        self._role.set(default)
        self._role.grid(row=0, column=1, sticky="w", pady=(2, 4))

        self._manual = ctk.CTkFrame(self, fg_color="transparent")
        self._manual.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._manual.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._manual, text="URL:", font=(UI_FONT, 12)).grid(
            row=0, column=0, padx=(0, 8), pady=2, sticky="w")
        self._url = ctk.CTkEntry(
            self._manual, height=30,
            placeholder_text="https://your-console.sentinelone.net")
        self._url.grid(row=0, column=1, sticky="ew", pady=2)
        self._url.bind("<FocusOut>", self._tidy_url)
        ctk.CTkLabel(self._manual, text="Token:", font=(UI_FONT, 12)).grid(
            row=1, column=0, padx=(0, 8), pady=2, sticky="w")
        self._token = ctk.CTkEntry(self._manual, height=30, show="•",
                                   placeholder_text="API token")
        self._token.grid(row=1, column=1, sticky="ew", pady=2)
        self._manual.grid_remove()

    def _tidy_url(self, _e=None):
        cleaned = parse_console_url(self._url.get())
        if cleaned != self._url.get():
            self._url.delete(0, "end")
            self._url.insert(0, cleaned)

    def _on_role(self, value):
        if value == "Manual":
            self._manual.grid()
        else:
            self._manual.grid_remove()

    def label(self) -> str:
        return self._role.get()

    def url(self) -> str:
        """Which console this picker points at, without connecting.

        Used to tie a cached plan to the console it was built against, so
        it is never restored for a different one.
        """
        role = self._role.get()
        if role in ("SOURCE", "DESTINATION"):
            api = (self.app.source_api if role == "SOURCE"
                   else self.app.dest_api)
            return str(getattr(api, "base_url", "") or "") if api else ""
        return parse_console_url(self._url.get())

    def api(self):
        """The S1API to use, or ValueError explaining what's missing."""
        role = self._role.get()
        if role in ("SOURCE", "DESTINATION"):
            api = (self.app.source_api if role == "SOURCE"
                   else self.app.dest_api)
            if not api:
                raise ValueError(
                    f"{role} console is not connected — connect it on the "
                    f"Connections page, or switch this tab to Manual.")
            return api
        url = parse_console_url(self._url.get())
        token = self._token.get().strip()
        if not url or not token:
            raise ValueError("Enter both a console URL and an API token.")
        return S1API(url, token)


# ═══════════════════════════════════════════════════════════════════════
#  UI building blocks
# ═══════════════════════════════════════════════════════════════════════

def _hex(colour) -> str:
    """One hex string from a CustomTkinter (light, dark) colour pair.

    Plain Tk widgets cannot take the pair, and the live feed rows have to
    be plain Tk: a CTkLabel queues canvas redraw work on every
    `configure`, and a few hundred of those is what froze the window.
    """
    if isinstance(colour, (tuple, list)):
        dark = str(ctk.get_appearance_mode()).lower() == "dark"
        return colour[1] if dark else colour[0]
    return str(colour)


def _bind_deep(widget, sequence, fn):
    """Bind on a container AND its children, so clicking a card works
    wherever on it you happen to land."""
    widget.bind(sequence, fn)
    for child in widget.winfo_children():
        _bind_deep(child, sequence, fn)


class _ChoiceDialog(ctk.CTkToplevel):
    """Tick what you want from a list the console searches for us.

    Scope ids are long, opaque and easy to mistype, and nobody knows
    them by heart. Asking the console and showing names next to the ids
    turns "paste the right number" into a choice.

    Big consoles rule out the obvious implementation twice over, so this
    breaks both habits:

    * **We never ask for the whole console.** `fetch(query, limit)` runs
      on a worker thread and lets the API do the matching, so opening
      costs one small page instead of a full cursor walk. Consoles with
      thousands of sites used to mean waiting for every one of them.
    * **We never build a widget per result.** Rows come from a fixed
      pool of plain Tk widgets, rebound on each render. Growing a
      `CTkScrollableFrame` is superlinear — measured here at 2.3s for 50
      rows, 112s for 200 and 14 minutes for 400, because every insert
      relayouts the whole tree. A pool of `PAGE` is built once and each
      render after that is a handful of `configure` calls.

    Ticks survive searching: something ticked and then filtered away
    stays ticked, because `_chosen` is keyed by id and outlives the rows
    on screen. The footer says how many are ticked but out of view, so
    the count never looks wrong.

    Call `ask()`; it returns the chosen ids, or None if cancelled.
    """

    PAGE = 50            # rows in the pool, and the page we ask for
    DEBOUNCE_MS = 300    # quiet time before a keystroke hits the API

    def __init__(self, master, title, fetch, chosen=(), note="",
                 noun="item"):
        super().__init__(master)
        self.title(title)
        self.geometry("560x560")
        self.minsize(440, 380)
        self._fetch = fetch
        self._noun = noun
        # dict, not set: insertion order is the order we hand back
        self._chosen = dict.fromkeys(
            str(c) for c in chosen if str(c).strip())
        self._shown: list = []       # [(id, name, sub)] currently rendered
        self._more = False           # console has more than we asked for
        self._gen = 0                # newest search wins, stale ones drop
        self._timer = None
        self._result = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text=title, anchor="w",
                     font=(UI_FONT, 15, "bold")).grid(
            row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        ctk.CTkLabel(self, text=note or "Search, then tick what you want.",
                     anchor="w", justify="left", wraplength=500,
                     font=(UI_FONT, 11), text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(2, 8))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=16)
        bar.grid_columnconfigure(0, weight=1)
        self._search = ctk.CTkEntry(bar, height=32,
                                    placeholder_text="Search by name…")
        self._search.grid(row=0, column=0, sticky="ew")
        self._search.bind("<KeyRelease>", self._queue_search)
        ctk.CTkButton(bar, text="All", width=54, height=30, font=(UI_FONT, 11),
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      command=lambda: self._set_all(True)).grid(
            row=0, column=1, padx=(8, 0))
        ctk.CTkButton(bar, text="None", width=54, height=30,
                      font=(UI_FONT, 11), fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER,
                      command=lambda: self._set_all(False)).grid(
            row=0, column=2, padx=(6, 0))

        self._build_list(row=3)

        self._status = ctk.CTkLabel(self, text="Searching the console…",
                                    anchor="w", font=(UI_FONT, 11),
                                    text_color=TEXT_FAINT)
        self._status.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 6))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 14))
        foot.grid_columnconfigure(0, weight=1)
        self._count = ctk.CTkLabel(foot, text="", anchor="w",
                                   font=(UI_FONT, 11),
                                   text_color=TEXT_MUTED)
        self._count.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(foot, text="Cancel", width=90, height=34,
                      fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      command=self._cancel).grid(row=0, column=1, padx=(0, 8))
        self._ok = ctk.CTkButton(foot, text="Use selection", width=140,
                                 height=34, font=(UI_FONT, 12, "bold"),
                                 fg_color=BRAND, hover_color=BRAND_HOVER,
                                 command=self._accept)
        self._ok.grid(row=0, column=2)

        self._tally()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._accept())
        # Paint an empty window first, then go and ask. The operator sees
        # the dialog immediately even when the console is slow.
        self.after(0, self._search_now)

    # ── the list: one canvas, one pool, built once ────────────────────

    def _build_list(self, row):
        wrap = ctk.CTkFrame(self, fg_color=CARD_ELEVATED,
                            corner_radius=RADIUS_MD)
        wrap.grid(row=row, column=0, sticky="nsew", padx=16, pady=(10, 4))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)
        bg = _hex(CARD_ELEVATED)
        self._canvas = tk.Canvas(wrap, highlightthickness=0, bd=0, bg=bg)
        self._canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scroll = ctk.CTkScrollbar(wrap, command=self._canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=6)
        self._canvas.configure(yscrollcommand=scroll.set)
        self._inner = tk.Frame(self._canvas, bg=bg)
        self._inner.grid_columnconfigure(0, weight=1)
        self._window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", lambda _e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(
            self._window, width=e.width))
        self._rows = [self._make_row(i, bg) for i in range(self.PAGE)]
        self._blank = tk.Label(self._inner, text="", bg=bg,
                               fg=_hex(TEXT_FAINT), anchor="w",
                               justify="left", font=(UI_FONT, 12))
        self._wheel(self._canvas)
        self._wheel(self._inner)

    def _make_row(self, slot, bg):
        var = tk.BooleanVar(value=False)
        frame = tk.Frame(self._inner, bg=bg)
        frame.grid_columnconfigure(0, weight=1)
        chk = tk.Checkbutton(
            frame, variable=var, text="", anchor="w", justify="left",
            bg=bg, fg=_hex(TEXT), activebackground=bg,
            activeforeground=_hex(TEXT), selectcolor=_hex(CARD),
            highlightthickness=0, bd=0, padx=4, font=(UI_FONT, 12),
            command=lambda s=slot: self._toggle(s))
        chk.grid(row=0, column=0, sticky="ew", padx=(6, 6))
        sub = tk.Label(frame, text="", bg=bg, fg=_hex(TEXT_FAINT),
                       anchor="w", justify="left", font=(MONO_FONT, 10))
        sub.grid(row=1, column=0, sticky="ew", padx=(30, 6))
        for w in (frame, chk, sub):
            self._wheel(w)
        return {"frame": frame, "var": var, "chk": chk, "sub": sub,
                "id": None, "sig": None, "placed": False}

    def _wheel(self, widget):
        def on_wheel(event):
            num = getattr(event, "num", None)
            if num == 4:
                step = -1
            elif num == 5:
                step = 1
            else:
                delta = getattr(event, "delta", 0)
                step = -int(delta / 120) if abs(delta) >= 120 else -int(delta)
                step = step or (-1 if delta > 0 else 1)
            self._canvas.yview_scroll(step, "units")
            return "break"
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(seq, on_wheel, add="+")

    def _render(self):
        """Rebind the pool. No widget is created or destroyed here."""
        rows = self._shown
        for i, row in enumerate(self._rows):
            if i >= len(rows):
                if row["placed"]:
                    row["frame"].grid_remove()
                    row["placed"] = False
                row["id"] = None
                continue
            ident, name, sub = rows[i]
            sig = (name, sub)
            if row["sig"] != sig:
                row["chk"].configure(text=name or ident)
                row["sub"].configure(text=sub or "")
                row["sig"] = sig
            row["id"] = ident
            # set() does not fire the Checkbutton command, so this cannot
            # loop back into _toggle and corrupt the selection
            row["var"].set(ident in self._chosen)
            if not row["placed"]:
                row["frame"].grid(row=i, column=0, sticky="ew", pady=1)
                row["placed"] = True
        if rows:
            self._blank.grid_remove()
        else:
            self._blank.configure(
                text=f"No {self._noun} matches that search."
                if self._search.get().strip()
                else f"No {self._noun} came back from the console.")
            self._blank.grid(row=self.PAGE, column=0, sticky="ew",
                             padx=12, pady=12)
        self._canvas.yview_moveto(0)
        self._tally()

    # ── searching: debounced, off-thread, newest wins ─────────────────

    def _queue_search(self, _event=None):
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = self.after(self.DEBOUNCE_MS, self._search_now)

    def _search_now(self):
        self._timer = None
        self._gen += 1
        gen = self._gen
        query = self._search.get().strip()
        self._status.configure(text="Searching the console…")

        # Ask for one more than we can show: that is how we know whether
        # to tell the operator there is more behind the search.
        def work():
            return list(self._fetch(query, self.PAGE + 1) or [])

        def done(items):
            if gen != self._gen:
                return           # a later keystroke already answered
            self._more = len(items) > self.PAGE
            self._shown = items[:self.PAGE]
            self._render()
            self._say()

        def failed(exc):
            if gen != self._gen:
                return
            self._shown = []
            self._render()
            self._status.configure(text=f"Could not search: {exc}")

        self._spawn(work, done, failed)

    def _spawn(self, work, done, failed):
        """Run `work` off-thread and answer on the UI thread.

        Deliberately not `run_async`: this dialog can be dismissed while
        a search is still in flight, and scheduling onto a destroyed
        widget throws from inside the worker. Tests override this to run
        inline, which is also why the search logic never touches threads
        directly.
        """
        def run():
            try:
                payload, err = work(), None
            except Exception as exc:          # noqa: BLE001 - reported in UI
                payload, err = None, exc
            try:
                self.after(0, lambda: failed(err) if err else done(payload))
            except Exception:
                pass          # dialog closed while we were searching
        threading.Thread(target=run, daemon=True).start()

    def _say(self):
        n = len(self._shown)
        if not n:
            self._status.configure(text="")
        elif self._more:
            self._status.configure(
                text=f"Showing the first {n}. Type a name to narrow it "
                     f"down — the console is doing the searching.")
        else:
            self._status.configure(
                text=f"Showing all {n} {self._noun}(s) that match.")

    def _set_all(self, value):
        """Applies to what is on screen, not to the whole console — with
        a search box in play, "All" must never tick what you filtered
        away and cannot see."""
        for ident, _n, _s in self._shown:
            if value:
                self._chosen[ident] = True
            else:
                self._chosen.pop(ident, None)
        self._render()

    def _toggle(self, slot):
        ident = self._rows[slot]["id"]
        if ident is None:
            return
        if self._rows[slot]["var"].get():
            self._chosen[ident] = True
        else:
            self._chosen.pop(ident, None)
        self._tally()

    def _tally(self):
        n = len(self._chosen)
        on_screen = sum(1 for i, _n, _s in self._shown if i in self._chosen)
        hidden = n - on_screen
        if not n:
            text = "Nothing ticked — that means everything"
        elif hidden:
            text = f"{n} ticked ({hidden} not shown by this search)"
        else:
            text = f"{n} ticked"
        self._count.configure(text=text)
        self._ok.configure(text="Use selection" if n else "Use all")

    # ── result ────────────────────────────────────────────────────────

    def _accept(self):
        self._result = list(self._chosen)
        self.destroy()

    def _cancel(self):
        self._result = None
        self.destroy()

    def ask(self):
        self._centre()
        self.after(60, self._grab)
        self.wait_window()
        return self._result

    def _centre(self):
        """Over the window that opened it, not the corner of the screen."""
        try:
            parent = self.master.winfo_toplevel()
            parent.update_idletasks()
            w, h = 560, 560
            x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
            self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    def _grab(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
            self._search.focus_set()
        except Exception:
            pass


class _StepBar(ctk.CTkFrame):
    """The workflow, made visible: numbered cards showing where you are,
    what is done, and what each step produced.

    A step that can't be done yet (no destination read, no test run) is
    shown locked with the reason, instead of failing when clicked.
    """

    def __init__(self, master, steps, on_select, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._on_select = on_select
        self._cards = []
        for i, (title, hint) in enumerate(steps):
            self.grid_columnconfigure(i * 2, weight=1)
            card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=RADIUS_MD,
                                border_width=1, border_color=BORDER)
            card.grid(row=0, column=i * 2, sticky="ew", pady=2)
            card.grid_columnconfigure(1, weight=1)

            badge = ctk.CTkLabel(card, text=str(i + 1), width=26, height=26,
                                 corner_radius=13, fg_color=NEUTRAL,
                                 text_color="#FFFFFF",
                                 font=(UI_FONT, 12, "bold"))
            badge.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=12)
            name = ctk.CTkLabel(card, text=title, anchor="w",
                                font=(UI_FONT, 13, "bold"))
            name.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 0))
            status = ctk.CTkLabel(card, text=hint, anchor="w",
                                  font=(UI_FONT, 11), text_color=TEXT_FAINT)
            status.grid(row=1, column=1, sticky="ew", padx=(0, 12),
                        pady=(0, 12))

            self._cards.append({"card": card, "badge": badge, "name": name,
                                "status": status, "state": "todo"})
            if i < len(steps) - 1:
                ctk.CTkLabel(self, text="→", font=(UI_FONT, 16),
                             text_color=TEXT_FAINT).grid(
                    row=0, column=i * 2 + 1, padx=8)

        for i, c in enumerate(self._cards):
            _bind_deep(c["card"], "<Button-1>", lambda _e, n=i: on_select(n))

    def set(self, index, state=None, caption=None):
        """state: todo | active | done | locked"""
        c = self._cards[index]
        if state:
            c["state"] = state
        if caption is not None and caption != c.get("caption"):
            c["caption"] = caption
            c["status"].configure(text=caption)
        st = c["state"]
        if st == c.get("painted"):
            return              # restyling costs a full redraw; skip it
        c["painted"] = st
        if st == "done":
            c["badge"].configure(text="✓", fg_color=GREEN)
            c["card"].configure(border_color=GREEN, fg_color=CARD)
            c["name"].configure(text_color=TEXT)
            c["status"].configure(text_color=GREEN)
        elif st == "active":
            c["badge"].configure(text=str(index + 1), fg_color=BRAND)
            c["card"].configure(border_color=BRAND, fg_color=CARD_ELEVATED)
            c["name"].configure(text_color=TEXT)
            c["status"].configure(text_color=TEXT_MUTED)
        elif st == "locked":
            c["badge"].configure(text="🔒", fg_color=NEUTRAL)
            c["card"].configure(border_color=BORDER, fg_color=CARD)
            c["name"].configure(text_color=TEXT_FAINT)
            c["status"].configure(text_color=TEXT_FAINT)
        else:
            c["badge"].configure(text=str(index + 1), fg_color=NEUTRAL)
            c["card"].configure(border_color=BORDER, fg_color=CARD)
            c["name"].configure(text_color=TEXT)
            c["status"].configure(text_color=TEXT_FAINT)

    def state(self, index) -> str:
        return self._cards[index]["state"]


class _Stats(ctk.CTkFrame):
    """A row of headline numbers. Figures are monospaced so columns line
    up and don't jitter as they update.

    Tiles are built once and then re-labelled. Destroying and rebuilding
    them on every update looks harmless, but creating CustomTkinter
    widgets from inside a redraw makes Tk re-enter `update_idletasks`,
    and during a live migration that cascade freezes the window.
    """

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", "transparent")
        # Until the first tile exists this frame has no children, and an
        # empty CTkFrame asks for 200px — a band of nothing between the
        # buttons and the results. It grows to fit the tiles once shown.
        kw.setdefault("height", 1)
        super().__init__(master, **kw)
        self._tiles = []

    def _tile(self, index):
        while len(self._tiles) <= index:
            i = len(self._tiles)
            frame = ctk.CTkFrame(self, fg_color=CARD_ELEVATED,
                                 corner_radius=RADIUS_MD)
            value = ctk.CTkLabel(frame, text="",
                                 font=(MONO_FONT, 20, "bold"))
            value.pack(anchor="w", padx=14, pady=(10, 0))
            label = ctk.CTkLabel(frame, text="", font=(UI_FONT, 11),
                                 text_color=TEXT_MUTED)
            label.pack(anchor="w", padx=14, pady=(0, 10))
            frame.grid(row=0, column=i, padx=(0, 8), pady=2, sticky="ew")
            frame.grid_remove()
            self.grid_columnconfigure(i, weight=1)
            self._tiles.append({"frame": frame, "value": value,
                                "label": label, "sig": None})
        return self._tiles[index]

    def show(self, items):
        """items: [(value, label, colour)]"""
        for i, (value, label, colour) in enumerate(items):
            tile = self._tile(i)
            sig = (str(value), label, colour or TEXT)
            if tile["sig"] != sig:
                tile["sig"] = sig
                tile["value"].configure(text=sig[0], text_color=sig[2])
                tile["label"].configure(text=label)
            tile["frame"].grid()
        for tile in self._tiles[len(items):]:
            tile["frame"].grid_remove()

    def clear(self):
        for tile in self._tiles:
            tile["frame"].grid_remove()


class _Table(ctk.CTkFrame):
    """Column header + zebra-striped scrollable rows.

    Run results used to be dumped into a monospace textbox; a real table
    makes a 384-row migration scannable.
    """

    def __init__(self, master, columns, weights=None, **kw):
        kw.setdefault("fg_color", CARD_ELEVATED)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        self.columns = columns
        self._weights = weights or [1] * len(columns)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        for j, col in enumerate(columns):
            head.grid_columnconfigure(j, weight=self._weights[j])
            ctk.CTkLabel(head, text=col.upper(), anchor="w",
                         font=(UI_FONT, 10, "bold"),
                         text_color=TEXT_FAINT).grid(
                row=0, column=j, sticky="ew", padx=4)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        for j in range(len(columns)):
            self._body.grid_columnconfigure(j, weight=self._weights[j])

    def clear(self, message=""):
        for w in self._body.winfo_children():
            w.destroy()
        if message:
            ctk.CTkLabel(self._body, text=message, font=(UI_FONT, 12),
                         text_color=TEXT_FAINT, justify="left",
                         wraplength=620).grid(
                row=0, column=0, columnspan=len(self.columns), sticky="w",
                padx=10, pady=14)

    def set_rows(self, rows, limit=400, colour_key=None):
        """rows: dicts keyed by column name. `colour_key(row)` may return a
        text colour for the whole row."""
        self.clear()
        for i, row in enumerate(rows[:limit]):
            bg = CARD if i % 2 else "transparent"
            colour = colour_key(row) if colour_key else None
            for j, col in enumerate(self.columns):
                value = row.get(col, "")
                ctk.CTkLabel(self._body, text=str(value)[:70], anchor="w",
                             fg_color=bg,
                             font=(MONO_FONT, 11) if isinstance(value, int)
                             else (UI_FONT, 11),
                             text_color=colour or TEXT).grid(
                    row=i, column=j, sticky="ew", padx=4, pady=1)
        if len(rows) > limit:
            ctk.CTkLabel(self._body,
                         text=f"… and {len(rows) - limit} more — the export "
                              f"has all of them",
                         font=(UI_FONT, 11), text_color=TEXT_FAINT).grid(
                row=limit, column=0, columnspan=len(self.columns),
                sticky="w", padx=10, pady=8)


class _Banner(ctk.CTkFrame):
    """An inline message with its own call to action — for the things that
    would otherwise be buried in a log, like name mismatches."""

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD_ELEVATED)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        self.grid_columnconfigure(1, weight=1)
        self._icon = ctk.CTkLabel(self, text="⚠", width=24,
                                  font=(UI_FONT, 16, "bold"), text_color=WARN)
        self._icon.grid(row=0, column=0, padx=(12, 6), pady=10)
        self._text = ctk.CTkLabel(self, text="", anchor="w", justify="left",
                                  font=(UI_FONT, 12), wraplength=560)
        self._text.grid(row=0, column=1, sticky="ew", pady=10)
        self._btn = ctk.CTkButton(self, text="", height=30, width=150,
                                  fg_color=WARN, hover_color=WARN_HOVER)
        self._btn.grid(row=0, column=2, padx=12, pady=10)
        self.grid_remove()

    def show(self, text, button=None, command=None, colour=WARN, icon="⚠"):
        self._icon.configure(text=icon, text_color=colour)
        self._text.configure(text=text)
        if button and command:
            self._btn.configure(text=button, command=command, fg_color=colour)
            self._btn.grid()
        else:
            self._btn.grid_remove()
        self.grid()

    def hide(self):
        self.grid_remove()


class _EventPump:
    """Carry events from a worker thread to the widgets, in batches.

    Tk may only be touched from the main thread, and a live migration can
    emit thousands of events — redrawing on each one makes the window
    unusable. Everything lands in a queue and is drained on a timer.
    """

    def __init__(self, widget, handler, interval: int = 90,
                 per_tick: int = 2000, on_flush=None):
        self._widget = widget
        self._handler = handler
        self._interval = interval
        self._per_tick = per_tick
        self._on_flush = on_flush
        self._q = queue.Queue()
        self._job = None

    def push(self, event):
        """Called from the worker thread."""
        self._q.put(event)

    def start(self):
        if self._job is None:
            self._tick()

    def stop(self):
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def drain(self):
        """Handle everything queued right now, then repaint once.

        The handler only updates state; drawing happens in `on_flush`, so
        a burst of ten thousand events costs one repaint instead of ten
        thousand. That is the difference between a live view and a frozen
        window.
        """
        seen = 0
        while seen < self._per_tick:
            try:
                event = self._q.get_nowait()
            except queue.Empty:
                break
            seen += 1
            try:
                self._handler(event)
            except Exception as exc:
                cli_log(f"live view: {exc}", "error")
        if seen and self._on_flush:
            try:
                self._on_flush()
            except Exception as exc:
                cli_log(f"live view: {exc}", "error")
        return seen

    def _tick(self):
        self.drain()
        self._job = self._widget.after(self._interval, self._tick)


class _FlowStrip(ctk.CTkFrame):
    """SOURCE ──▶ DESTINATION, with the agents counted as they cross.

    The one picture that answers "what is happening right now": which
    console they leave, which they join, and how far through we are.
    """

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", RADIUS_MD)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        super().__init__(master, **kw)
        self.grid_columnconfigure(1, weight=1)

        self._src = self._console(0, "SOURCE", GREEN)
        middle = ctk.CTkFrame(self, fg_color="transparent")
        middle.grid(row=0, column=1, sticky="ew", padx=16, pady=14)
        middle.grid_columnconfigure(0, weight=1)
        self._moving = ctk.CTkLabel(middle, text="idle",
                                    font=(UI_FONT, 12, "bold"),
                                    text_color=TEXT_MUTED)
        self._moving.grid(row=0, column=0, sticky="ew")
        self._arrow = ctk.CTkProgressBar(middle, height=8,
                                         progress_color=BRAND)
        self._arrow.grid(row=1, column=0, sticky="ew", pady=4)
        self._arrow.set(0)
        self._where = ctk.CTkLabel(middle, text="", font=(UI_FONT, 11),
                                   text_color=TEXT_FAINT)
        self._where.grid(row=2, column=0, sticky="ew")
        self._dst = self._console(2, "DESTINATION", ACCENT)

    def _console(self, column, role, colour):
        box = ctk.CTkFrame(self, fg_color=CARD_ELEVATED,
                           corner_radius=RADIUS_SM)
        box.grid(row=0, column=column, padx=14, pady=14)
        ctk.CTkLabel(box, text=role, font=(UI_FONT, 10, "bold"),
                     text_color=colour).pack(padx=18, pady=(10, 0))
        name = ctk.CTkLabel(box, text="—", font=(UI_FONT, 13, "bold"))
        name.pack(padx=18)
        count = ctk.CTkLabel(box, text="", font=(MONO_FONT, 11),
                             text_color=TEXT_MUTED)
        count.pack(padx=18, pady=(0, 10))
        return {"name": name, "count": count}

    def consoles(self, source: str, destination: str):
        self._src["name"].configure(text=source or "—")
        self._dst["name"].configure(text=destination or "—")

    def totals(self, left: str = "", right: str = ""):
        self._src["count"].configure(text=left)
        self._dst["count"].configure(text=right)

    def progress(self, done: int, total: int, moving: str = "",
                 where: str = ""):
        self._arrow.set((done / total) if total else 0)
        self._moving.configure(
            text=moving or (f"{done} of {total}" if total else "idle"),
            text_color=TEXT if total else TEXT_MUTED)
        self._where.configure(text=where)

    def finish(self, text: str, colour=GREEN):
        self._arrow.set(1)
        self._arrow.configure(progress_color=colour)
        self._moving.configure(text=text, text_color=colour)

    def reset(self):
        self._arrow.configure(progress_color=BRAND)
        self._arrow.set(0)
        self._moving.configure(text="idle", text_color=TEXT_MUTED)
        self._where.configure(text="")
        self.totals("", "")


class _MatchList(ctk.CTkScrollableFrame):
    """One line per source scope, paired with where it will land.

    The whole point of step 2: the operator reads their own account, site
    and group names back and sees, per row, whether the destination has a
    twin for it. A flat table of totals cannot answer that.
    """

    GLYPH = {"ready": ("✓", GREEN), "done": ("✓", TEXT_FAINT),
             "blocked": ("✕", ACCENT)}

    def __init__(self, master, on_fix=None, **kw):
        kw.setdefault("fg_color", CARD_ELEVATED)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._on_fix = on_fix
        self._rows = {}
        self._filter = "all"
        self._placeholder = None

    def clear(self, message=""):
        for w in self.winfo_children():
            w.destroy()
        self._rows = {}
        self._placeholder = None
        if message:
            self._placeholder = ctk.CTkLabel(
                self, text=message, font=(UI_FONT, 12), justify="left",
                text_color=TEXT_FAINT, wraplength=640)
            self._placeholder.grid(row=0, column=0, sticky="w", padx=14,
                                   pady=16)

    def set_filter(self, value):
        self._filter = value
        for entry in self._rows.values():
            if self._wanted(entry["row"]):
                entry["card"].grid()
            else:
                entry["card"].grid_remove()

    def _wanted(self, row):
        if self._filter == "all":
            return True
        if self._filter == "ready":
            return row["state"] == "ready"
        return row["state"] == "blocked"

    def _count_text(self, row):
        if row["state"] == "ready":
            # Until the count lands this is the group's own total, which
            # includes agents that already moved — say so rather than
            # quietly showing a number that is about to change.
            suffix = "" if row.get("counted") else " (so far)"
            return f"{row['Agents']} agent(s){suffix}"
        return f"{row['Total']} agent(s)" if row["Total"] else ""

    def _note_text(self, row):
        return row["reason"] or (f"token from the destination "
                                 f"{row['token_from']}"
                                 if row["token_from"] else "")

    def upsert(self, row):
        """Draw a row, or refresh the one already drawn for that scope.

        The pairing pass and the counting pass both report the same scope,
        so rows are keyed rather than appended.
        """
        entry = self._rows.get(row["key"])
        if entry is not None:
            self._refresh(entry, row)
            return

        if self._placeholder is not None:
            self._placeholder.destroy()
            self._placeholder = None
        index = len(self._rows)
        card = ctk.CTkFrame(self, fg_color=CARD if index % 2 else
                            "transparent", corner_radius=RADIUS_SM)
        card.grid(row=index, column=0, sticky="ew", padx=6, pady=1)
        card.grid_columnconfigure(1, weight=3)
        card.grid_columnconfigure(3, weight=3)

        glyph, colour = self.GLYPH.get(row["state"], ("•", TEXT_MUTED))
        mark = ctk.CTkLabel(card, text=glyph, width=18, text_color=colour,
                            font=(UI_FONT, 13, "bold"))
        mark.grid(row=0, column=0, rowspan=2, padx=(10, 6), pady=6)

        source = f"{row['Account']}  ›  {row['Site']}  ›  {row['Group']}"
        ctk.CTkLabel(card, text=source, anchor="w", font=(UI_FONT, 12),
                     text_color=TEXT).grid(row=0, column=1, sticky="ew")
        arrow = ctk.CTkLabel(
            card, text="──▶" if row["state"] != "blocked" else "──✕",
            width=34, text_color=colour, font=(MONO_FONT, 12, "bold"))
        arrow.grid(row=0, column=2, padx=8)
        dest = ctk.CTkLabel(
            card, text=(row["Destination"] if row["state"] != "blocked"
                        else row["Status"]),
            anchor="w", font=(UI_FONT, 12),
            text_color=TEXT if row["state"] != "blocked" else ACCENT)
        dest.grid(row=0, column=3, sticky="ew")

        count = ctk.CTkLabel(card, text=self._count_text(row), width=130,
                             anchor="e", font=(MONO_FONT, 11),
                             text_color=TEXT_MUTED)
        count.grid(row=0, column=4, padx=(8, 10))

        note = ctk.CTkLabel(card, text=self._note_text(row), anchor="w",
                            justify="left", font=(UI_FONT, 10),
                            text_color=TEXT_FAINT, wraplength=700)
        note.grid(row=1, column=1, columnspan=4, sticky="ew", pady=(0, 6))

        fix = ctk.CTkButton(card, text="Fix name", width=76, height=24,
                            font=(UI_FONT, 11), fg_color=WARN,
                            hover_color=WARN_HOVER, command=self._on_fix)
        entry = {"row": row, "card": card, "mark": mark, "arrow": arrow,
                 "dest": dest, "count": count, "note": note, "fix": fix}
        self._rows[row["key"]] = entry
        self._refresh(entry, row)

    def _refresh(self, entry, row):
        entry["row"] = row
        glyph, colour = self.GLYPH.get(row["state"], ("•", TEXT_MUTED))
        blocked = row["state"] == "blocked"
        entry["mark"].configure(text=glyph, text_color=colour)
        entry["arrow"].configure(text="──✕" if blocked else "──▶",
                                 text_color=colour)
        entry["dest"].configure(
            text=row["Status"] if blocked else row["Destination"],
            text_color=ACCENT if blocked else TEXT)
        entry["count"].configure(text=self._count_text(row))
        entry["note"].configure(text=self._note_text(row))
        if blocked and row.get("kind") and self._on_fix:
            entry["fix"].grid(row=0, column=5, padx=(0, 10))
        else:
            entry["fix"].grid_remove()
        if self._wanted(row):
            entry["card"].grid()
        else:
            entry["card"].grid_remove()


class _LiveFeed(ctk.CTkFrame):
    """The agents in the run, as a window onto what is happening now.

    A row per agent would mean six CustomTkinter widgets per machine —
    on a ten-thousand-agent run that is sixty thousand widgets and the
    window stops responding. So the rows here are a FIXED POOL that is
    built once and re-used: the records are plain dicts, and a repaint
    just re-labels `VISIBLE` rows. Cost is the same for 50 agents as for
    50,000, and the export still carries every one of them.
    """

    PILL = {
        "queued": ("queued", TEXT_FAINT),
        "sending": ("sending…", BRAND),
        "moved": ("moved", GREEN),
        "pending": ("pending", WARN),
        "failed": ("FAILED", ACCENT),
    }
    VISIBLE = 40

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD_ELEVATED)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._records = {}
        self._order = []
        self._filter = "all"
        self._follow = True
        self._bg = (_hex(CARD_ELEVATED), _hex(CARD))
        self._fg = {"text": _hex(TEXT), "muted": _hex(TEXT_MUTED),
                    "faint": _hex(TEXT_FAINT), "failed": _hex(ACCENT)}
        self._pill_fg = {k: _hex(v[1]) for k, v in self.PILL.items()}
        self._pool = [self._make_row(i) for i in range(self.VISIBLE)]
        self._note = ctk.CTkLabel(self, text="", anchor="w",
                                  font=(UI_FONT, 11), text_color=TEXT_FAINT)
        self._note.grid(row=self.VISIBLE + 1, column=0, sticky="ew",
                        padx=14, pady=(4, 8))
        self.clear("Nothing has been sent yet.")

    # ── the pool ──────────────────────────────────────────────────────

    def _make_row(self, index):
        bg = self._bg[index % 2]
        card = tk.Frame(self, bg=bg)
        card.grid(row=index, column=0, sticky="ew", padx=6, pady=1)
        card.grid_columnconfigure(3, weight=1)

        def cell(col, chars, font, fg, **grid):
            lab = tk.Label(card, text="", anchor="w", bg=bg, fg=fg,
                           font=font, bd=0, highlightthickness=0,
                           width=chars)
            lab.grid(row=0, column=col, **grid)
            return lab

        pill = cell(0, 9, (UI_FONT, 11, "bold"), self._fg["faint"],
                    padx=(12, 8), pady=4)
        name = cell(1, 24, (MONO_FONT, 11), self._fg["text"], sticky="w")
        os_name = cell(2, 20, (UI_FONT, 11), self._fg["muted"], padx=8)
        detail = cell(3, 0, (UI_FONT, 11), self._fg["faint"],
                      sticky="ew", padx=(0, 12))
        card.grid_remove()
        return {"card": card, "pill": pill, "name": name,
                "os": os_name, "detail": detail, "sig": None,
                "shown": False}

    # ── data in ───────────────────────────────────────────────────────

    def clear(self, message=""):
        self._records = {}
        self._order = []
        for row in self._pool:
            row["card"].grid_remove()
            row["sig"] = None
            row["shown"] = False
        self._note.configure(text=message)

    def put(self, rec):
        """Record one agent's latest state. Draws nothing — see render()."""
        aid = rec.get("id")
        if not aid:
            return
        if aid not in self._records:
            self._order.append(aid)
        self._records[aid] = rec

    def set_filter(self, value):
        self._filter = value
        self.render()

    def set_follow(self, follow: bool):
        """Follow the tail while the run is live; hold still once done."""
        self._follow = bool(follow)

    # ── drawing ───────────────────────────────────────────────────────

    def _wanted(self, rec):
        return self._filter == "all" or rec.get("Result") == self._filter

    def render(self):
        matching = [self._records[i] for i in self._order
                    if self._wanted(self._records[i])]
        total = len(matching)
        # While the run is live the interesting end is the newest; once
        # it stops, the top of the filtered list is what gets read.
        shown = (matching[-self.VISIBLE:] if self._follow
                 else matching[:self.VISIBLE])

        for row, rec in zip(self._pool, shown):
            state = rec.get("Result", "queued")
            sig = (state, rec.get("Computer", ""), rec.get("OS", ""),
                   rec.get("Detail", ""))
            # Re-configuring a widget marks it dirty and CustomTkinter
            # answers by re-entering update_idletasks; on a busy run that
            # cascade is what froze the window. So only touch what moved.
            if row["sig"] != sig:
                row["sig"] = sig
                row["pill"].configure(
                    text=self.PILL.get(state, (state, None))[0],
                    fg=self._pill_fg.get(state, self._fg["muted"]))
                row["name"].configure(text=sig[1])
                row["os"].configure(text=sig[2])
                row["detail"].configure(
                    text=sig[3],
                    fg=self._fg["failed"] if state == "failed"
                    else self._fg["faint"])
            if not row["shown"]:
                row["shown"] = True
                row["card"].grid()
        for row in self._pool[len(shown):]:
            if row["shown"]:
                row["shown"] = False
                row["card"].grid_remove()

        if not total:
            note = ("No agent matches this filter." if self._records
                    else "Nothing has been sent yet.")
        elif total > self.VISIBLE:
            where = "most recent" if self._follow else "first"
            note = (f"Showing the {where} {self.VISIBLE} of {total} — the "
                    f"counters above cover them all, and Export writes out "
                    f"every agent.")
        else:
            note = f"{total} agent(s)."
        if self._note.cget("text") != note:
            self._note.configure(text=note)


class _CommandLog(ctk.CTkFrame):
    """The requests actually going out, as they go out.

    Operators asked to see the command, not a paraphrase of it — this is
    the endpoint, the filter and how many ids rode along. Tokens are
    masked because this pane ends up in screenshots.
    """

    MAX_LINES = 200

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD_ELEVATED)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="API CALLS", anchor="w",
                     font=(UI_FONT, 10, "bold"), text_color=TEXT_FAINT).grid(
            row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._box = ctk.CTkTextbox(self, font=(MONO_FONT, 11), height=110,
                                   fg_color="transparent", wrap="none",
                                   activate_scrollbars=True)
        self._box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self._box.configure(state="disabled")
        self._lines = 0
        self._pending = []

    def add(self, text):
        """Queue a line. Written on the next `flush`, because each write
        to the textbox costs a redraw of far more than the textbox."""
        self._pending.append(text)

    def flush(self):
        if not self._pending:
            return
        block, self._pending = "\n".join(self._pending) + "\n", []
        self._box.configure(state="normal")
        self._box.insert("end", block)
        self._lines += block.count("\n")
        if self._lines > self.MAX_LINES:
            cut = self._lines - self.MAX_LINES
            self._box.delete("1.0", f"{cut + 1}.0")
            self._lines = self.MAX_LINES
        self._box.see("end")
        self._box.configure(state="disabled")

    def clear(self):
        self._pending = []
        self._box.configure(state="normal")
        self._box.delete("1.0", "end")
        self._box.configure(state="disabled")
        self._lines = 0


class _Form(ctk.CTkFrame):
    """A labelled form card.

    Every field gets a visible label AND persistent helper text underneath
    — placeholder-only labels and hover-only "?" tooltips both hide the
    thing the operator most needs to know (what blank means).
    """

    BUTTON_W = 88        # so fields with and without one line up

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", RADIUS_MD)
        super().__init__(master, **kw)
        # The input takes a quarter of any spare width and the trailing
        # column soaks up the rest. Letting it take all of it strands the
        # label at one edge of a wide window and the button at the other.
        self.grid_columnconfigure(1, weight=1, minsize=240)
        self.grid_columnconfigure(3, weight=3)
        ctk.CTkFrame(self, fg_color="transparent", width=1, height=1).grid(
            row=0, column=3)
        self._row = 0

    def field(self, label, placeholder="", helper="", button=None, show=None):
        r = self._row
        ctk.CTkLabel(self, text=label, anchor="w",
                     font=(UI_FONT, 12, "bold")).grid(
            row=r, column=0, sticky="w", padx=(14, 10), pady=(12, 0))
        entry = ctk.CTkEntry(self, placeholder_text=placeholder, height=34)
        if show:
            entry.configure(show=show)
        entry.grid(row=r, column=1, sticky="ew", pady=(12, 0))
        if button:
            text, cmd = button
            ctk.CTkButton(self, text=text, width=self.BUTTON_W, height=32,
                          fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                          font=(UI_FONT, 12), command=cmd).grid(
                row=r, column=2, padx=(8, 14), pady=(12, 0))
        else:
            # Height 1, because an empty CTkFrame defaults to 200px tall
            # and would stretch this row — leaving the helper text
            # stranded half a panel below the box it describes.
            ctk.CTkFrame(self, fg_color="transparent",
                         width=self.BUTTON_W, height=1).grid(
                row=r, column=2, padx=(8, 14))
        if helper:
            ctk.CTkLabel(self, text=helper, anchor="w", justify="left",
                         font=(UI_FONT, 11), text_color=TEXT_FAINT).grid(
                row=r + 1, column=1, columnspan=2, sticky="w", pady=(3, 0))
        self._row += 2
        return entry

    def block(self, widget, pad=(10, 12)):
        widget.grid(row=self._row, column=0, columnspan=3, sticky="ew",
                    padx=14, pady=pad)
        self._row += 1
        return widget

    def pad(self, height=10):
        ctk.CTkFrame(self, fg_color="transparent",
                     width=1, height=height).grid(row=self._row, column=0)
        self._row += 1


class AgentMigratorPage(ctk.CTkFrame):
    """Agent migration as a guided three-step flow.

    Read the destination → match the source against it → migrate, each
    step gated on the one before it.

    Two things the old build could not answer, which this one puts on
    screen: "did it find MY accounts, sites and groups, and where is each
    one going?" (step 2 lists every source scope beside its destination
    twin, or the reason there isn't one) and "what is happening to my
    agents right now?" (step 3 names each machine as it is sent and shows
    the console's own verdict on it, including why one failed).

    There is no dry-run switch. Step 2 cannot move anything, step 3 only
    moves what step 2 listed, and its button says how many.
    """

    STEPS = [
        ("Read destination", "Not started"),
        ("Match scopes", "Read the destination first"),
        ("Migrate", "Match the scopes first"),
    ]

    # Seconds between counter/flow repaints during a live run.
    COUNTS_EVERY = 0.3

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.log = _ConsoleProxy(app)
        self._map_data = None
        self._map_path = ""
        self._plan = None           # last source→destination match plan
        self._plan_saved_at = ""    # when that plan was cached, if it was
        self._report = None         # last live run
        self._last_counts_paint = 0.0
        self._status = None
        self._live_counts = {"moved": 0, "pending": 0, "failed": 0,
                             "sent": 0, "total": 0}
        self._stop = threading.Event()
        self._sched_job = None
        self._sched_when = None
        self._panels = {}
        self._current = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self.steps = _StepBar(self, self.STEPS, self._on_step)
        self.steps.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))

        self._host = ctk.CTkFrame(self, fg_color="transparent")
        self._host.grid(row=2, column=0, sticky="nsew", padx=20)
        self._host.grid_columnconfigure(0, weight=1)
        self._host.grid_rowconfigure(0, weight=1)

        self._panels["map"] = self._build_panel_map()
        self._panels["match"] = self._build_panel_match()
        self._panels["live"] = self._build_panel_live()
        self._panels["status"] = self._build_panel_status()
        self._panels["schedule"] = self._build_panel_schedule()

        self._build_tools()
        self._paint_live_intent()
        self._refresh_gates()
        self._show("map")

    # ── chrome ────────────────────────────────────────────────────────

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        bar.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(left, text="Agent Migration",
                     font=(UI_FONT, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            left,
            text="Move agents to the destination console, keeping every "
                 "site and group where it was.",
            font=(UI_FONT, 13), text_color=TEXT_MUTED).pack(anchor="w")

        self._conn_box = ctk.CTkFrame(bar, fg_color="transparent")
        self._conn_box.grid(row=0, column=1, sticky="e")
        self._src_chip = self._chip(self._conn_box, "SOURCE", GREEN)
        self._dst_chip = self._chip(self._conn_box, "DESTINATION", ACCENT)

    @staticmethod
    def _chip(parent, role, colour):
        chip = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=RADIUS_SM,
                            border_width=1, border_color=BORDER)
        chip.pack(side="left", padx=(8, 0))
        dot = ctk.CTkLabel(chip, text="●", width=12, text_color=TEXT_FAINT,
                           font=(UI_FONT, 12, "bold"))
        dot.pack(side="left", padx=(10, 4), pady=6)
        ctk.CTkLabel(chip, text=role, font=(UI_FONT, 10, "bold"),
                     text_color=colour).pack(side="left", pady=6)
        state = ctk.CTkLabel(chip, text="not connected", font=(UI_FONT, 11),
                             text_color=TEXT_FAINT)
        state.pack(side="left", padx=(6, 12), pady=6)
        return {"dot": dot, "state": state}

    def _refresh_chips(self):
        for chip, api in ((self._src_chip, self.app.source_api),
                          (self._dst_chip, self.app.dest_api)):
            if api is not None:
                host = str(getattr(api, "base_url", "")).replace(
                    "https://", "").split(".")[0]
                chip["dot"].configure(text_color=GREEN)
                chip["state"].configure(text=host or "connected",
                                        text_color=TEXT_MUTED)
            else:
                chip["dot"].configure(text_color=TEXT_FAINT)
                chip["state"].configure(text="not connected",
                                        text_color=TEXT_FAINT)

    def _build_tools(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 14))
        ctk.CTkLabel(bar, text="ALSO", font=(UI_FONT, 10, "bold"),
                     text_color=TEXT_FAINT).pack(side="left", padx=(2, 10))
        self._tool_btns = {}
        for key, label in (("status", "📈  Status report"),
                           ("schedule", "⏱  Schedule a run")):
            btn = ctk.CTkButton(
                bar, text=label, height=32, width=170, font=(UI_FONT, 12),
                fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                command=lambda k=key: self._show(k))
            btn.pack(side="left", padx=(0, 8))
            self._tool_btns[key] = btn
        self._sched_badge = ctk.CTkLabel(bar, text="", font=(UI_FONT, 12),
                                         text_color=ACCENT)
        self._sched_badge.pack(side="left", padx=8)

    # ── panel switching + gating ──────────────────────────────────────

    def _show(self, name):
        if self._current:
            self._panels[self._current].grid_remove()
        self._panels[name].grid(row=0, column=0, sticky="nsew")
        self._current = name
        order = {"map": 0, "match": 1, "live": 2}
        for i in range(3):
            st = self.steps.state(i)
            if st == "active":
                self.steps.set(i, "todo")
        if name in order:
            i = order[name]
            if self.steps.state(i) != "done":
                self.steps.set(i, "active")
        for key, btn in self._tool_btns.items():
            btn.configure(fg_color=BRAND if key == name else NEUTRAL,
                          hover_color=BRAND_HOVER if key == name
                          else NEUTRAL_HOVER)

    def _on_step(self, index):
        if index == 1 and not self._map_data:
            self.log.log("Read the destination first — step 2 needs the "
                         "sites, groups and tokens it produces.")
            self._show("map")
            return
        if index == 2 and not self._plan:
            self.log.log("Match the scopes first — step 3 only unlocks once "
                         "step 2 has shown what maps to what.")
            self._show("match" if self._map_data else "map")
            return
        self._show(("map", "match", "live")[index])

    def _refresh_gates(self):
        """Keep the stepper honest about what can be done right now."""
        if self._map_data:
            accounts, sites, groups = map_counts(self._map_data)
            self.steps.set(0, "done",
                           f"{accounts} accounts · {sites} sites · "
                           f"{groups} groups")
        else:
            self.steps.set(0, None, "Not started")

        if not self._map_data:
            self.steps.set(1, "locked", "Read the destination first")
        elif self._plan:
            self.steps.set(1, "done",
                           f"{self._plan['ready']} groups matched · "
                           f"{self._plan['blocked']} cannot")
        else:
            self.steps.set(1, "todo", "Ready — nothing will be touched")

        if not self._plan:
            self.steps.set(2, "locked", "Match the scopes first")
        elif self._report:
            self.steps.set(2, "done",
                           f"{self._report['moved']} moved · "
                           f"{self._report['failed']} failed")
        else:
            self.steps.set(2, "todo",
                           f"Ready to move {self._plan['agents']} agents")
        if self._current in ("map", "match", "live"):
            i = {"map": 0, "match": 1, "live": 2}[self._current]
            if self.steps.state(i) not in ("done",):
                self.steps.set(i, "active")

    # ── shared bits ───────────────────────────────────────────────────

    def _say(self, msg):
        self.after(0, lambda m=msg: self.log.log(m))

    def _panel(self, title, blurb):
        """A panel frame with its heading; returns (frame, next_row)."""
        frame = ctk.CTkFrame(self._host, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, anchor="w",
                     font=(UI_FONT, 16, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        ctk.CTkLabel(frame, text=blurb, anchor="w", justify="left",
                     wraplength=820, font=(UI_FONT, 12),
                     text_color=TEXT_MUTED).grid(
            row=1, column=0, sticky="w", pady=(0, 10))
        return frame

    def _advanced(self, form, build):
        """Progressive disclosure: the console override and file paths stay
        folded away until someone actually needs them."""
        holder = ctk.CTkFrame(form, fg_color="transparent")
        holder.grid_columnconfigure(0, weight=1)
        body = ctk.CTkFrame(holder, fg_color="transparent")
        body.grid_columnconfigure(1, weight=1)
        shown = {"v": False}

        btn = ctk.CTkButton(holder, text="⚙  Advanced  ▸", height=28,
                            width=140, anchor="w", font=(UI_FONT, 11),
                            fg_color="transparent", hover_color=CARD_ELEVATED,
                            text_color=TEXT_MUTED)

        def toggle():
            shown["v"] = not shown["v"]
            btn.configure(text="⚙  Advanced  ▾" if shown["v"]
                          else "⚙  Advanced  ▸")
            if shown["v"]:
                body.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            else:
                body.grid_remove()

        btn.configure(command=toggle)
        btn.grid(row=0, column=0, sticky="w")
        build(body)
        form.block(holder, pad=(8, 12))
        return body

    @staticmethod
    def _actions(parent, row):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="ew", pady=(10, 6))
        return bar

    @staticmethod
    def _fill(entry, ids):
        entry.delete(0, "end")
        entry.insert(0, ", ".join(ids))

    def _choose_accounts(self, picker, entry):
        """Tick accounts the console finds for us.

        The dialog opens straight away and does its own searching on a
        worker thread, so a console with thousands of accounts costs one
        small page rather than a full walk before anything appears.
        """
        try:
            api = picker.api()
        except ValueError as e:
            messagebox.showwarning("Console", str(e))
            return

        def fetch(query, limit):
            return [(str(a["id"]), a.get("name") or "(unnamed)",
                     f"id {a['id']}")
                    for a in (api.search_accounts(query, limit) or [])
                    if a.get("id")]

        chosen = _ChoiceDialog(
            self.winfo_toplevel(), "Choose accounts", fetch,
            chosen=split_ids(entry.get()), noun="account",
            note="Tick the accounts to work on. Leave everything unticked "
                 "to cover them all.").ask()
        if chosen is None:
            return
        self._fill(entry, chosen)
        self.log.log(f"Accounts: {', '.join(chosen) or 'all of them'}")

    def _choose_sites(self, picker, account_entry, site_entry):
        """Sites for whichever accounts are in the field beside this one."""
        try:
            api = picker.api()
        except ValueError as e:
            messagebox.showwarning("Console", str(e))
            return
        account_ids = split_ids(account_entry.get())
        scope = (f"in the {len(account_ids)} account(s) beside this field"
                 if account_ids else "across every account this token sees")

        def fetch(query, limit):
            out = []
            for s in (api.search_sites(
                    query, ",".join(account_ids), limit) or []):
                ident = str(s.get("id", ""))
                if not ident:
                    continue
                # The site payload already carries its account name, so
                # there is no need to walk /accounts just to label a row.
                acct = s.get("accountName") or ""
                out.append((ident, s.get("name") or "(unnamed)",
                            f"{acct} · id {ident}" if acct else f"id {ident}"))
            return out

        chosen = _ChoiceDialog(
            self.winfo_toplevel(), "Choose sites", fetch,
            chosen=split_ids(site_entry.get()), noun="site",
            note=f"Searching {scope}. Tick the sites to include — leave "
                 f"everything unticked for all of them.").ask()
        if chosen is None:
            return
        self._fill(site_entry, chosen)
        self.log.log(f"Sites: {', '.join(chosen) or 'all of them'}")

    # ── step 1 · read the destination ─────────────────────────────────

    def _build_panel_map(self):
        p = self._panel(
            "Step 1 — Read the destination",
            "Lists every site and group on the DESTINATION console with its "
            "registration token and saves them to a file. Step 2 uses that "
            "file to send each source group to the group of the same name.")
        p.grid_rowconfigure(4, weight=1)

        form = _Form(p)
        form.grid(row=2, column=0, sticky="ew")
        self.map_account = form.field(
            "Destination accounts", "click Choose, or type ids",
            "Leave blank to read every account this token can see.",
            button=("Choose…", lambda: self._choose_accounts(
                self.map_conn, self.map_account)))
        self.map_site = form.field(
            "Only these sites", "click Choose, or type ids",
            "Leave blank to include every site in those accounts.",
            button=("Choose…", lambda: self._choose_sites(
                self.map_conn, self.map_account, self.map_site)))

        def extras(body):
            self.map_conn = _ConnPicker(body, self.app, default="DESTINATION")
            self.map_conn.grid(row=0, column=0, columnspan=2, sticky="ew",
                               pady=(0, 6))
            ctk.CTkLabel(body, text="Save to", font=(UI_FONT, 12),
                         anchor="w").grid(row=1, column=0, sticky="w",
                                          padx=(0, 10))
            self.map_file = ctk.CTkEntry(
                body, height=32, placeholder_text="…/destination-map.json")
            self.map_file.grid(row=1, column=1, sticky="ew")
            ctk.CTkButton(body, text="Browse", width=88, height=30,
                          fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                          font=(UI_FONT, 12),
                          command=self._pick_map_target).grid(
                row=1, column=2, padx=(8, 0))

        self._advanced(form, extras)

        bar = self._actions(p, 3)
        self.map_btn = ctk.CTkButton(
            bar, text="Read destination", height=40, width=190,
            font=(UI_FONT, 13, "bold"), fg_color=BRAND,
            hover_color=BRAND_HOVER, command=self._build_map)
        self.map_btn.pack(side="left")
        self.map_stop_btn = ctk.CTkButton(
            bar, text="Stop", height=40, width=80, fg_color=NEUTRAL,
            hover_color=NEUTRAL_HOVER, state="disabled",
            command=self._stop_map)
        self.map_stop_btn.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="Open a saved file", height=40, width=150,
                      fg_color="transparent", hover_color=CARD_ELEVATED,
                      text_color=TEXT_MUTED, font=(UI_FONT, 12),
                      command=self._load_map).pack(side="left")
        self.map_prog = ctk.CTkProgressBar(bar, mode="indeterminate",
                                           height=6, width=160)

        result = ctk.CTkFrame(p, fg_color="transparent")
        result.grid(row=4, column=0, sticky="nsew", pady=(4, 12))
        result.grid_columnconfigure(0, weight=1)
        result.grid_rowconfigure(2, weight=1)
        self.map_stats = _Stats(result)
        self.map_stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.map_banner = _Banner(result)
        self.map_banner.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.map_banner.hide()
        self.map_tree = _Table(result, ["Scope", "Name", "Registration token"],
                               weights=[1, 4, 3])
        self.map_tree.grid(row=2, column=0, sticky="nsew")
        self.map_tree.clear("Nothing read yet — press “Read destination” and "
                            "the sites and groups found will be listed here.")
        return p

    def _pick_map_target(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")],
            initialfile="destination-map.json")
        if path:
            self.map_file.delete(0, "end")
            self.map_file.insert(0, path)

    def _map_rows(self, data):
        rows = []
        for acct in data or []:
            rows.append({"Scope": "account", "Name": acct.get("name", ""),
                         "Registration token": ""})
            for site in acct.get("sites") or []:
                rows.append({
                    "Scope": "  site", "Name": site.get("name", ""),
                    "Registration token": "yes" if site.get("token")
                    else "MISSING"})
                for grp in site.get("groups") or []:
                    rows.append({
                        "Scope": "    group", "Name": grp.get("name", ""),
                        "Registration token": "yes" if grp.get("token")
                        else "uses the site's"})
        return rows

    def _set_map(self, data, path):
        self._map_data = data
        self._map_path = path
        accounts, sites, groups = map_counts(data)
        stranded = sites_without_token(data)
        missing = len(stranded)
        self.map_stats.show([
            (accounts, "accounts", TEXT),
            (sites, "sites", TEXT),
            (groups, "groups", TEXT),
            (missing, "sites without a token", WARN if missing else GREEN),
        ])
        self.map_tree.set_rows(
            self._map_rows(data),
            colour_key=lambda r: WARN
            if r["Registration token"] == "MISSING" else None)
        if missing:
            names = ", ".join(f"{a} / {s}" for a, s in stranded[:4])
            more = f" (+{missing - 4} more)" if missing > 4 else ""
            self.map_banner.show(
                f"{missing} site(s) have no registration token, and neither "
                f"do some of their groups — agents cannot be moved into "
                f"them: {names}{more}. Create a token on the destination "
                f"console, then read it again.")
        else:
            self.map_banner.hide()
        self.map_file.delete(0, "end")
        self.map_file.insert(0, path)
        self.match_file.delete(0, "end")
        self.match_file.insert(0, path)
        self._plan = None
        self._plan_saved_at = ""
        self._report = None
        self.match_list.clear(
            "Nothing matched yet — press “Find matches” and every source "
            "account, site and group will be listed here next to the "
            "destination scope it maps to.")
        self._paint_restored_hint(False)
        # A plan already built for this exact map and scope is still good,
        # so step 3 can be usable without walking the console again.
        if not self._restore_plan():
            self._refresh_gates()

    def _build_map(self):
        try:
            api = self.map_conn.api()
        except ValueError as e:
            messagebox.showwarning("Console", str(e))
            return
        account_ids = self.map_account.get().strip()
        site_id = self.map_site.get().strip()
        path = self.map_file.get().strip() or os.path.join(
            os.path.expanduser("~"),
            f"s1-destination-map-{datetime.now():%Y%m%d-%H%M}.json")

        self.log.log("Reading destination scopes"
                     + (f" (accounts: {account_ids})" if account_ids
                        else " (every account this token can see)") + "…")
        self._stop.clear()
        self._set_mapping(True)

        def do():
            data = build_scope_map(api, account_ids, site_id, log=self._say,
                                   should_stop=self._stop.is_set)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return data, path

        def done(result):
            self._set_mapping(False)
            data, written = result
            self._set_map(data, written)
            accounts, sites, groups = map_counts(data)
            cli_log(f"Destination read: {accounts} account(s), {sites} "
                    f"site(s), {groups} group(s) → {written}", "success")
            self.app.log_audit("agent_map_build", sites=sites, groups=groups,
                               path=written)
            self._show("match")

        def fail(e):
            self._set_mapping(False)
            self.map_banner.show(f"Could not read the destination: {e}",
                                 colour=ACCENT, icon="✕")

        run_async(self, do, done, fail)

    def _set_mapping(self, running: bool):
        self.map_btn.configure(
            state="disabled" if running else "normal",
            text="Reading…" if running else "Read destination")
        self.map_stop_btn.configure(state="normal" if running else "disabled")
        if running:
            self.map_prog.pack(side="left", padx=12)
            self.map_prog.start()
        else:
            self.map_prog.stop()
            self.map_prog.pack_forget()

    def _stop_map(self):
        self._stop.set()
        self.map_stop_btn.configure(state="disabled")
        self.log.log("Stopping — finishing the current account…")

    def _load_map(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Could not read that file", str(e))
            return
        if not isinstance(data, list):
            messagebox.showerror(
                "Not a destination file",
                "Expected the JSON list of accounts that step 1 writes.")
            return
        self._set_map(data, path)
        cli_log(f"Loaded destination file {path}.", "info")

    # ── step 2 · match the source to the destination ──────────────────

    def _build_panel_match(self):
        p = self._panel(
            "Step 2 — Match the source to the destination",
            "Reads every account, site and group on the SOURCE console and "
            "pairs each one with the same-named scope on the destination. "
            "Nothing moves — this is the plan, and you can see exactly "
            "which of your scopes were found and which were not.")
        p.grid_rowconfigure(4, weight=1)

        form = _Form(p)
        form.grid(row=2, column=0, sticky="ew")
        self.match_account = form.field(
            "Source accounts", "click Choose, or type ids",
            "Leave blank to migrate every account this token can see.",
            button=("Choose…", lambda: self._choose_accounts(
                self.match_conn, self.match_account)))
        self.match_site = form.field(
            "Only these sites", "click Choose, or type ids",
            "Leave blank to walk every site in those accounts.",
            button=("Choose…", lambda: self._choose_sites(
                self.match_conn, self.match_account, self.match_site)))

        def extras(body):
            self.match_conn = _ConnPicker(body, self.app, default="SOURCE")
            self.match_conn.grid(row=0, column=0, columnspan=3, sticky="ew",
                                 pady=(0, 6))
            ctk.CTkLabel(body, text="Destination file", font=(UI_FONT, 12),
                         anchor="w").grid(row=1, column=0, sticky="w",
                                          padx=(0, 10))
            self.match_file = ctk.CTkEntry(
                body, height=32, placeholder_text="…/destination-map.json")
            self.match_file.grid(row=1, column=1, sticky="ew")
            ctk.CTkButton(body, text="Browse", width=88, height=30,
                          fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                          font=(UI_FONT, 12),
                          command=self._pick_map_file).grid(
                row=1, column=2, padx=(8, 0))

        self._advanced(form, extras)

        bar = self._actions(p, 3)
        self.match_btn = ctk.CTkButton(
            bar, text="Find matches", height=40, width=190,
            font=(UI_FONT, 13, "bold"), fg_color=BRAND,
            hover_color=BRAND_HOVER, command=self._run_match)
        self.match_btn.pack(side="left")
        self.match_stop_btn = ctk.CTkButton(
            bar, text="Stop", height=40, width=80, fg_color=NEUTRAL,
            hover_color=NEUTRAL_HOVER, state="disabled",
            command=self._stop_run)
        self.match_stop_btn.pack(side="left", padx=8)
        self.match_export_btn = ctk.CTkButton(
            bar, text="Export", height=40, width=100, fg_color="transparent",
            hover_color=CARD_ELEVATED, text_color=TEXT_MUTED,
            font=(UI_FONT, 12), state="disabled",
            command=self._export_match)
        self.match_export_btn.pack(side="left")
        self.match_prog = ctk.CTkProgressBar(bar, mode="indeterminate",
                                             height=6, width=160)

        result = ctk.CTkFrame(p, fg_color="transparent")
        result.grid(row=4, column=0, sticky="nsew", pady=(4, 12))
        result.grid_columnconfigure(0, weight=1)
        result.grid_rowconfigure(3, weight=1)
        self.match_stats = _Stats(result)
        self.match_stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.match_banner = _Banner(result)
        self.match_banner.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.match_banner.hide()

        filter_row = ctk.CTkFrame(result, fg_color="transparent")
        filter_row.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.match_filter = ctk.CTkSegmentedButton(
            filter_row, values=["Everything", "Will migrate",
                                "Cannot migrate"],
            font=(UI_FONT, 11), command=self._on_match_filter)
        self.match_filter.set("Everything")
        self.match_filter.pack(side="left")
        self.match_age = ctk.CTkLabel(filter_row, text="", font=(UI_FONT, 11),
                                      text_color=TEXT_FAINT)
        self.match_age.pack(side="left", padx=12)

        self.match_list = _MatchList(result, on_fix=self._fix_names)
        self.match_list.grid(row=3, column=0, sticky="nsew")
        self.match_list.clear(
            "Nothing matched yet — press “Find matches” and every source "
            "account, site and group will be listed here next to the "
            "destination scope it maps to.")
        return p

    def _on_match_filter(self, value):
        self.match_list.set_filter(
            {"Everything": "all", "Will migrate": "ready"}.get(value,
                                                               "blocked"))

    def _pick_map_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self.match_file.delete(0, "end")
            self.match_file.insert(0, path)

    def _read_map_file(self):
        path = self.match_file.get().strip()
        if self._map_data is not None and path == self._map_path:
            return self._map_data, path
        if not path:
            raise ValueError("Run step 1, or point this at a destination "
                             "file it wrote earlier.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("That file is not a destination map.")
        return data, path

    def _stop_run(self):
        self._stop.set()
        self.match_stop_btn.configure(state="disabled")
        self.live_stop_btn.configure(state="disabled")
        self.log.log("Stopping — finishing the current group…")

    def _run_match(self):
        try:
            api = self.match_conn.api()
            map_data, _path = self._read_map_file()
        except (ValueError, OSError, json.JSONDecodeError) as e:
            messagebox.showwarning("Cannot match", str(e))
            return

        account_ids = self.match_account.get().strip()
        site_id = self.match_site.get().strip()
        self._stop.clear()
        self._set_running("match", True)
        self.match_list.clear()
        self.match_filter.set("Everything")
        self.match_list.set_filter("all")
        self.match_stats.show([(0, "reading the source…", TEXT_MUTED)])
        self.log.log("Matching source scopes against the destination — "
                     "nothing will be moved…")

        pump = _EventPump(self, self._on_match_row)
        pump.start()

        def do():
            return build_match_plan(
                api, map_data, account_ids, site_id, log=self._say,
                should_stop=self._stop.is_set, on_row=pump.push)

        def done(plan):
            pump.drain()
            pump.stop()
            self._set_running("match", False)
            self._plan = plan
            self._plan_saved_at = ""
            self._report = None
            self._remember_plan(plan, account_ids, site_id)
            self._paint_plan(plan)
            self._refresh_gates()
            self._paint_live_intent()
            cli_log(f"Matched {plan['ready']} group(s) covering "
                    f"{plan['agents']} agent(s); {plan['blocked']} scope(s) "
                    f"cannot migrate.",
                    "warning" if plan["blocked"] else "success")

        def fail(e):
            pump.stop()
            self._set_running("match", False)
            self.match_banner.show(f"Could not read the source: {e}",
                                   colour=ACCENT, icon="✕")

        run_async(self, do, done, fail)

    def _on_match_row(self, row):
        """One resolved source group, straight from the worker thread.

        Fires twice per scope — once when it is paired, once when its
        count lands — so the list keys rows rather than appending.
        """
        self.match_list.upsert(row)

    # ── remembering the plan ──────────────────────────────────────────

    def _fingerprint(self, account_ids, site_id):
        return plan_fingerprint(self.match_conn.url(), account_ids, site_id,
                                self._map_path, self._map_data)

    def _remember_plan(self, plan, account_ids, site_id):
        """Cache a complete plan so the next session skips the walk."""
        if plan.get("stopped") or not plan.get("rows"):
            return
        try:
            save_plan(plan, self._fingerprint(account_ids, site_id))
        except OSError as e:
            self.log.log(f"Could not cache the match plan: {e}")

    def _restore_plan(self):
        """Bring back the last matching plan for these exact inputs."""
        if not self._map_data:
            return False
        try:
            fingerprint = self._fingerprint(self.match_account.get().strip(),
                                            self.match_site.get().strip())
            plan, saved_at = load_plan(fingerprint, self._map_data)
        except Exception:
            return False
        if not plan:
            return False
        self._plan = plan
        self._plan_saved_at = saved_at
        self.match_list.clear()
        for row in plan["rows"]:
            self.match_list.upsert(row)
        self._paint_plan(plan, restored=True)
        self._refresh_gates()
        self._paint_live_intent()
        cli_log(f"Restored the match from {plan_age(saved_at)} — "
                f"{plan['ready']} group(s), {plan['agents']} agent(s). "
                f"Re-run step 2 if the consoles have changed.", "info")
        return True

    def _paint_plan(self, plan, restored=False):
        blockers = plan_blockers(plan)
        self.match_stats.show([
            (plan["agents"], "agents will migrate",
             GREEN if plan["agents"] else TEXT_MUTED),
            (plan["ready"], "groups matched", TEXT),
            (plan["blocked"], "cannot migrate",
             ACCENT if plan["blocked"] else GREEN),
            (plan["accounts"], "accounts read", TEXT),
        ])
        if not plan["rows"]:
            self.match_list.clear(
                "No source scope produced a row. Either the accounts are "
                "empty or the site filter excluded everything.")
        self.match_export_btn.configure(
            state="normal" if plan["rows"] else "disabled")

        mismatches = len(plan["unmatched"])
        if mismatches:
            kinds = ", ".join(f"{len(v)} {k}" for k, v in blockers.items())
            self.match_banner.show(
                f"{mismatches} source scope(s) have no same-named twin on "
                f"the destination ({kinds}), so their agents would stay "
                f"put. Point each one at its counterpart and they join the "
                f"run.", button="Fix names", command=self._fix_names)
        elif plan["blocked"]:
            self.match_banner.show(
                f"{plan['blocked']} scope(s) cannot migrate — the rows "
                f"marked ✕ say why.", colour=ACCENT, icon="✕")
        elif plan["stopped"]:
            self.match_banner.show("Stopped early, so this is a partial "
                                   "plan.", icon="■")
        elif restored:
            # A remembered plan is only as true as the console was then,
            # so its age is stated and re-running is one click away.
            self.match_banner.show(
                f"Restored the match from {plan_age(self._plan_saved_at)} — "
                f"no need to wait for it again. Re-run it if sites, groups "
                f"or agents have changed since.",
                colour=BRAND, icon="↺", button="Match again",
                command=self._run_match)
        else:
            self.match_banner.hide()
        self._paint_restored_hint(restored)
        # The console keeps the full text version, for pasting into a ticket.
        self.log.log(plan_summary_text(plan))

    def _paint_restored_hint(self, restored):
        if restored and self._plan_saved_at:
            self.match_age.configure(
                text=f"↺  remembered from {plan_age(self._plan_saved_at)}")
        else:
            self.match_age.configure(text="")

    def _set_running(self, which, running):
        btn, stop, prog, idle = {
            "match": (self.match_btn, self.match_stop_btn, self.match_prog,
                      "Find matches"),
            "live": (self.live_btn, self.live_stop_btn, self.live_prog,
                     self._live_label()),
        }[which]
        btn.configure(state="disabled" if running else "normal",
                      text="Working…" if running else idle)
        stop.configure(state="normal" if running else "disabled")
        if running:
            prog.pack(side="left", padx=12)
            prog.start()
        else:
            prog.stop()
            prog.pack_forget()

    def _export_match(self):
        plan = self._plan or {}
        if not plan.get("rows"):
            messagebox.showinfo("Nothing to export", "Find the matches "
                                                     "first.")
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        export_agent_report(build_match_report(plan, self._map_path),
                            default_name=f"s1-agent-match-plan-{ts}")

    def _fix_names(self):
        unmatched = (self._plan or {}).get("unmatched") or []
        if not unmatched:
            messagebox.showinfo("Nothing to fix", "No name mismatches.")
            return
        try:
            map_data, map_path = self._read_map_file()
        except (ValueError, OSError, json.JSONDecodeError) as e:
            messagebox.showwarning("Cannot open the destination file", str(e))
            return
        _NameFixDialog(self, unmatched, map_data, map_path, self._after_fix)

    def _after_fix(self, map_data, map_path, renamed):
        self._set_map(map_data, map_path)
        self.match_banner.show(
            f"{renamed} name(s) matched up. Find the matches again to pick "
            f"up the scopes that were being skipped.", icon="✓", colour=GREEN)
        cli_log(f"Destination file updated: {renamed} name(s) aligned.",
                "success")
        self._show("match")

    # ── step 3 · migrate, and watch it happen ─────────────────────────

    def _build_panel_live(self):
        p = self._panel(
            "Step 3 — Migrate",
            "Sends each matched group to its destination token and then "
            "reads every agent back, so you can watch them move and see "
            "the console's own reason for any that don't.")
        p.grid_rowconfigure(6, weight=1)

        self.flow = _FlowStrip(p)
        self.flow.grid(row=2, column=0, sticky="ew")

        bar = self._actions(p, 3)
        self.live_btn = ctk.CTkButton(
            bar, text="Migrate", height=44, width=260,
            font=(UI_FONT, 14, "bold"), fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self._run_live)
        self.live_btn.pack(side="left")
        self.live_stop_btn = ctk.CTkButton(
            bar, text="Stop", height=44, width=80, fg_color=NEUTRAL,
            hover_color=NEUTRAL_HOVER, state="disabled",
            command=self._stop_run)
        self.live_stop_btn.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="Back to the matches", height=44, width=150,
                      fg_color="transparent", hover_color=CARD_ELEVATED,
                      text_color=TEXT_MUTED, font=(UI_FONT, 12),
                      command=lambda: self._show("match")).pack(side="left")
        self.live_export_btn = ctk.CTkButton(
            bar, text="Export", height=44, width=100, fg_color="transparent",
            hover_color=CARD_ELEVATED, text_color=TEXT_MUTED,
            font=(UI_FONT, 12), state="disabled", command=self._export_live)
        self.live_export_btn.pack(side="left")
        self.live_prog = ctk.CTkProgressBar(bar, mode="indeterminate",
                                            height=6, width=140)

        self.verify_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            p, text="Confirm each agent on the destination after sending",
            variable=self.verify_var, font=(UI_FONT, 12),
            progress_color=GREEN).grid(row=4, column=0, sticky="w",
                                       pady=(2, 0))
        ctk.CTkLabel(p,
                     text="The move endpoint only answers with a count. "
                          "Reading each agent back is what turns that into "
                          "“moved”, “pending” or “failed” per machine — "
                          "one extra call per 100 agents.",
                     font=(UI_FONT, 11), text_color=TEXT_FAINT,
                     justify="left", wraplength=780).grid(
            row=5, column=0, sticky="w", pady=(0, 8))

        result = ctk.CTkFrame(p, fg_color="transparent")
        result.grid(row=6, column=0, sticky="nsew", pady=(4, 12))
        result.grid_columnconfigure(0, weight=1)
        result.grid_rowconfigure(4, weight=1)
        self.live_stats = _Stats(result)
        self.live_stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.live_banner = _Banner(result)
        self.live_banner.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.live_banner.hide()
        self.cmd_log = _CommandLog(result)
        self.cmd_log.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.live_filter = ctk.CTkSegmentedButton(
            result, values=["All agents", "Moved", "Pending", "Failed"],
            font=(UI_FONT, 11), command=self._on_live_filter)
        self.live_filter.set("All agents")
        self.live_filter.grid(row=3, column=0, sticky="w", pady=(0, 6))

        self.live_feed = _LiveFeed(result)
        self.live_feed.grid(row=4, column=0, sticky="nsew")
        self.live_feed.clear("Every agent will appear here as it is sent, "
                             "with what the console said about it.")
        return p

    def _on_live_filter(self, value):
        self.live_feed.set_filter(
            {"All agents": "all", "Moved": "moved",
             "Pending": "pending"}.get(value, "failed"))

    def _live_label(self):
        n = (self._plan or {}).get("agents", 0)
        return f"Migrate {n} agent(s) now" if n else "Migrate"

    def _paint_live_intent(self):
        """Say exactly what the button is about to do — the number comes
        from the match plan, so it can't be a surprise."""
        src = self._console_name(self.app.source_api)
        dst = self._console_name(self.app.dest_api)
        self.flow.consoles(src, dst)
        if not self._plan:
            self.flow.totals("nothing planned", "")
            self.flow.progress(0, 0, "run step 2 first")
            self.live_btn.configure(state="disabled", text="Migrate")
            return
        n = self._plan.get("agents", 0)
        self.flow.totals(f"{n} agent(s) to move",
                         f"{self._plan.get('ready', 0)} group(s) waiting")
        blocked = self._plan.get("blocked", 0)
        self.flow.progress(
            0, 0, f"{n} ready" if n else "nothing to move",
            f"{blocked} scope(s) will be skipped" if blocked else "")
        self.live_btn.configure(state="normal" if n else "disabled",
                                text=self._live_label())

    @staticmethod
    def _console_name(api):
        if api is None:
            return "—"
        return str(getattr(api, "base_url", "")).replace(
            "https://", "").split(".")[0] or "connected"

    def _run_live(self, scheduled: bool = False):
        if not self._plan:
            messagebox.showinfo("Match first",
                                "Run step 2 so you can see what will move.")
            return
        try:
            api = self.match_conn.api()
        except ValueError as e:
            if scheduled:
                cli_log(f"Scheduled migration could not start: {e}", "error")
                return
            messagebox.showwarning("Cannot migrate", str(e))
            return

        planned = self._plan.get("agents", 0)
        if not scheduled and not messagebox.askyesno(
                "Migrate for real",
                f"Move {planned} agent(s) across "
                f"{self._plan.get('ready', 0)} group(s) to the destination "
                f"in:\n\n{self._map_path}\n\nThis cannot be undone from "
                f"here — agents would have to be migrated back. Continue?"):
            return

        rows = list(self._plan["rows"])
        verify = bool(self.verify_var.get())
        self._stop.clear()
        self._set_running("live", True)
        self._live_counts = {"moved": 0, "pending": 0, "failed": 0,
                             "sent": 0, "total": planned}
        self.live_feed.clear("Waiting for the first batch…")
        self.live_feed.set_follow(True)
        self.live_filter.set("All agents")
        self.live_feed.set_filter("all")
        self.cmd_log.clear()
        self.live_banner.hide()
        self.flow.reset()
        self.flow.consoles(self._console_name(self.app.source_api),
                           self._console_name(self.app.dest_api))
        self._paint_live_counts()
        cli_log("LIVE agent migration starting…", "cmd")

        pump = _EventPump(self, self._on_live_event,
                          on_flush=self._paint_live_view)
        pump.start()

        def do():
            return run_live_migration(
                api, rows, on_event=pump.push,
                should_stop=self._stop.is_set, verify=verify)

        def done(run):
            pump.drain()
            pump.stop()
            self._paint_live_view(force=True)
            self._set_running("live", False)
            self._report = run
            self._finish_live(run, scheduled)

        def fail(e):
            pump.stop()
            self._set_running("live", False)
            self.flow.finish("failed", ACCENT)
            self.live_banner.show(f"The migration failed: {e}", colour=ACCENT,
                                  icon="✕")

        run_async(self, do, done, fail)

    # ── the live view ─────────────────────────────────────────────────

    def _on_live_event(self, event):
        """One event from the running migration, on the main thread."""
        kind = event["type"]
        if kind == "start":
            self._live_counts["total"] = event["agents"]
            self.flow.totals(f"{event['agents']} agent(s) to move",
                             f"{event['groups']} group(s)")
        elif kind == "group":
            row = event["row"]
            self.flow.progress(
                self._live_counts["sent"], self._live_counts["total"],
                where=f"group {event['index']} of {event['total']} — "
                      f"{where_of(row)}  ──▶  {row['Destination']}")
        elif kind == "request":
            flt = event["filter"]
            self.cmd_log.add(
                f"▸ POST {event['endpoint']}  ids={event['count']}  "
                f"groupIds={flt.get('groupIds')}  token={event['token']}"
                + (f"  batch {event['batch']}/{event['of']}"
                   if event["of"] > 1 else ""))
        elif kind == "response":
            if event["ok"]:
                self.cmd_log.add(f"  ✓ accepted {event['affected']} of "
                                 f"{event['of']}")
            else:
                self.cmd_log.add(f"  ✕ {event['error']}")
        elif kind == "error":
            self.cmd_log.add(f"  ✕ {event['where']}: {event['error']}")
        elif kind == "roster":
            for rec in event["recs"]:
                self.live_feed.put(rec)
        elif kind == "agent":
            rec = event["rec"]
            self.live_feed.put(rec)
            state = rec["Result"]
            if state in self._live_counts:
                self._live_counts[state] += 1
                self._live_counts["sent"] += 1

    def _paint_live_view(self, force: bool = False):
        """Repaint once per batch of events, not once per agent.

        The feed is a fixed pool and costs almost nothing, so it follows
        every batch. The counters and the flow strip each cost tens of
        milliseconds — CustomTkinter redraws far more than the widget you
        touched — so they are held to a few times a second. `force` is
        used at the end so the final numbers are never a frame behind.
        """
        self.cmd_log.flush()
        self.live_feed.render()
        now = time.monotonic()
        if force or now - self._last_counts_paint >= self.COUNTS_EVERY:
            self._last_counts_paint = now
            self._paint_live_counts()

    def _paint_live_counts(self):
        c = self._live_counts
        done = c["moved"] + c["pending"] + c["failed"]
        left = max(0, c["total"] - done)
        self.live_stats.show([
            (c["moved"], "moved", GREEN if c["moved"] else TEXT_MUTED),
            (c["pending"], "pending check-in", WARN if c["pending"]
             else TEXT_MUTED),
            (c["failed"], "failed", ACCENT if c["failed"] else GREEN),
            (left, "still to go", TEXT),
        ])
        self.flow.progress(done, c["total"],
                           moving=f"{done} of {c['total']} processed")

    def _finish_live(self, run, scheduled):
        moved, pending = run["moved"], run["pending"]
        failed, errors = run["failed"], len(run["errors"])
        self.live_export_btn.configure(
            state="normal" if run["agents"] else "disabled")
        self._refresh_gates()
        # The run is over, so stop chasing the tail and read from the top.
        self.live_feed.set_follow(False)
        if failed:
            self.live_filter.set("Failed")
            self.live_feed.set_filter("failed")
        else:
            self.live_feed.render()
        if run["stopped"]:
            self.flow.finish("stopped", WARN)
        elif failed or errors:
            self.flow.finish(f"{moved} moved, {failed} failed", WARN)
        else:
            self.flow.finish(f"{moved} moved", GREEN)
        self.flow.totals("", f"{moved} confirmed")

        if failed:
            self.live_banner.show(
                f"{failed} agent(s) did not migrate — the list below is "
                f"showing them, each with the console's own reason.",
                colour=ACCENT, icon="✕")
        elif not run["verified"] and (moved or pending):
            self.live_banner.show(
                "Sent, but not confirmed per agent — “Confirm each agent” "
                "was off. Use the Status report to check they arrived.",
                icon="■")
        elif pending:
            self.live_banner.show(
                f"{pending} agent(s) were accepted but have not checked in "
                f"yet. They move on their next connection — re-run the "
                f"Status report later to confirm.", icon="■", colour=WARN)
        elif run["stopped"]:
            self.live_banner.show("Stopped early, so this is partial.",
                                  icon="■")
        else:
            self.live_banner.hide()

        level = "warning" if (failed or errors) else "success"
        cli_log(f"Migration finished: {moved} moved, {pending} pending, "
                f"{failed} failed.", level)
        self.log.log(live_summary_text(run))
        self.app.log_audit(
            "agent_mapped_migrate", dry_run=False,
            candidates=len(run["agents"]), moved=moved, pending=pending,
            failed=failed, errors=errors)
        if not scheduled:
            messagebox.showinfo(
                "Migration finished",
                f"{moved} agent(s) confirmed on the destination.\n"
                f"{pending} accepted, waiting to check in.\n"
                f"{failed} failed.\n\nThe Status report confirms the final "
                f"picture once the agents have re-registered.")

    def _export_live(self):
        run = self._report or {}
        if not run.get("agents"):
            messagebox.showinfo("Nothing to export", "Run the migration "
                                                     "first.")
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        export_agent_report(
            build_live_report(run, source=self.match_conn.url(),
                              map_path=self._map_path),
            default_name=f"s1-agent-live-run-{ts}")

    # ── tool · status report ──────────────────────────────────────────

    def _build_panel_status(self):
        p = self._panel(
            "Status report",
            "Counts every agent in scope by its console-migration status — "
            "the report you hand back after a migration window.")
        p.grid_rowconfigure(4, weight=1)

        form = _Form(p)
        form.grid(row=2, column=0, sticky="ew")
        self.status_account = form.field(
            "Accounts", "click Choose, or type ids",
            "Leave blank to report on the whole console.",
            button=("Choose…", lambda: self._choose_accounts(
                self.status_conn, self.status_account)))
        self.status_site = form.field(
            "Only these sites", "click Choose, or type ids",
            "Naming a site overrides the accounts above.",
            button=("Choose…", lambda: self._choose_sites(
                self.status_conn, self.status_account, self.status_site)))

        def extras(body):
            self.status_conn = _ConnPicker(body, self.app, default="SOURCE")
            self.status_conn.grid(row=0, column=0, columnspan=2, sticky="ew")
            self.pass_var = ctk.BooleanVar(value=False)
            ctk.CTkSwitch(body, text="Include passphrases",
                          variable=self.pass_var, font=(UI_FONT, 12),
                          progress_color=WARN,
                          command=self._on_passphrase_toggle).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
            ctk.CTkLabel(body,
                         text="Fetches each agent's uninstall passphrase from "
                              "the source — one API call per agent, so it can "
                              "take a while on a large scope. SentinelOne "
                              "records every passphrase fetch in the source "
                              "console's activity log, and the export becomes "
                              "sensitive. Off unless the customer needs them.",
                         font=(UI_FONT, 11), text_color=TEXT_FAINT,
                         justify="left", wraplength=560).grid(
                row=2, column=0, columnspan=2, sticky="w")

        self._advanced(form, extras)

        bar = self._actions(p, 3)
        self.status_btn = ctk.CTkButton(
            bar, text="Run report", height=40, width=190,
            font=(UI_FONT, 13, "bold"), fg_color=BRAND,
            hover_color=BRAND_HOVER, command=self._run_status)
        self.status_btn.pack(side="left")
        self.status_export_btn = ctk.CTkButton(
            bar, text="Export", height=40, width=100, fg_color="transparent",
            hover_color=CARD_ELEVATED, text_color=TEXT_MUTED,
            font=(UI_FONT, 12), state="disabled", command=self._export_status)
        self.status_export_btn.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="← Back to the migration", height=40,
                      width=180, fg_color="transparent",
                      hover_color=CARD_ELEVATED, text_color=TEXT_MUTED,
                      font=(UI_FONT, 12),
                      command=self._back_to_flow).pack(side="right")
        self.status_prog = ctk.CTkProgressBar(bar, mode="indeterminate",
                                              height=6, width=160)

        result = ctk.CTkFrame(p, fg_color="transparent")
        result.grid(row=4, column=0, sticky="nsew", pady=(4, 12))
        result.grid_columnconfigure(0, weight=1)
        result.grid_rowconfigure(1, weight=1)
        self.status_stats = _Stats(result)
        self.status_stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.status_table = _Table(
            result, ["Computer Name", "Migration Status", "Site", "Group",
                     "Decommissioned"], weights=[3, 2, 2, 2, 1])
        self.status_table.grid(row=1, column=0, sticky="nsew")
        self.status_table.clear("No report yet.")
        return p

    def _back_to_flow(self):
        self._show("live" if self._plan else
                   ("match" if self._map_data else "map"))

    def _on_passphrase_toggle(self):
        if self.pass_var.get():
            self.log.log(
                "Passphrases: one API call per agent (slow on a large scope), "
                "each fetch is written to the source console's activity log, "
                "and the exported report becomes sensitive.")

    def _run_status(self):
        try:
            api = self.status_conn.api()
        except ValueError as e:
            messagebox.showwarning("Console", str(e))
            return
        account_ids = self.status_account.get().strip()
        site_id = self.status_site.get().strip()
        if not account_ids and not site_id and not messagebox.askyesno(
                "Whole console",
                "No account or site given, so this reports on EVERY agent "
                "the token can see. On a large console that is a lot of "
                "paging.\n\nContinue?"):
            return
        fetch = bool(self.pass_var.get())
        if fetch and not messagebox.askyesno(
                "Fetch passphrases?",
                "Including passphrases reads each agent's uninstall passphrase "
                "from the source console.\n\n"
                "•  One API call per agent — this can take a long time on a "
                "large scope.\n"
                "•  SentinelOne records every passphrase fetch in the source "
                "console's ACTIVITY LOG.\n"
                "•  The exported report will contain secrets — treat it as "
                "sensitive.\n\nContinue?"):
            return

        self._stop.clear()
        self.status_btn.configure(state="disabled", text="Running…")
        self.status_prog.pack(side="left", padx=12)
        self.status_prog.start()
        self.status_table.clear("Counting…")

        def do():
            return count_agents_by_status(
                api, account_ids, site_id, fetch, log=self._say,
                should_stop=self._stop.is_set)

        def done(result):
            self._finish_status()
            self._status = result
            counts = result.get("counts") or {}
            decom = len(result.get("decommissioned") or [])
            self.status_stats.show([
                (counts.get("Migrated", 0), "migrated", GREEN),
                (counts.get("Pending", 0), "pending", WARN),
                (counts.get("Failed", 0), "failed",
                 ACCENT if counts.get("Failed") else TEXT_MUTED),
                (counts.get("N/A", 0), "not applicable", TEXT_MUTED),
                (decom, "decommissioned", TEXT_MUTED),
            ])
            rows = list(result.get("agents") or []) + \
                list(result.get("decommissioned") or [])
            if rows:
                self.status_table.set_rows(rows)
            else:
                self.status_table.clear("No agents in that scope.")
            self.status_export_btn.configure(
                state="normal" if rows else "disabled")
            self.log.log(status_summary_text(result))
            cli_log(f"Status report: {sum(counts.values())} agent(s).",
                    "success")

        def fail(e):
            self._finish_status()
            self.status_table.clear(f"The report failed: {e}")

        run_async(self, do, done, fail)

    def _finish_status(self):
        self.status_btn.configure(state="normal", text="Run report")
        self.status_prog.stop()
        self.status_prog.pack_forget()

    def _export_status(self):
        result = self._status or {}
        if not (result.get("agents") or result.get("decommissioned")):
            messagebox.showinfo("Nothing to export", "Run the report first.")
            return
        scope = (self.status_site.get().strip()
                 or self.status_account.get().strip() or "whole console")
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        export_agent_report(
            build_status_report(result, console=self.status_conn.url(),
                                scope=scope,
                                passphrases=bool(self.pass_var.get())),
            default_name=f"s1-agent-status-{ts}")

    # ── tool · scheduler ──────────────────────────────────────────────

    def _build_panel_schedule(self):
        p = self._panel(
            "Schedule the migration",
            "Runs step 3 unattended at a time you choose, using this "
            "computer's clock. It migrates exactly what your last test run "
            "found, so do the test first. The app must stay open, awake and "
            "on VPN until it fires.")

        form = _Form(p)
        form.grid(row=2, column=0, sticky="ew")
        soon = datetime.now() + timedelta(hours=1)
        self.sched_date = form.field("Date", "YYYY-MM-DD",
                                     "Your computer's local date.")
        self.sched_date.insert(0, soon.strftime("%Y-%m-%d"))
        self.sched_time = form.field("Time", "HH:MM (24-hour)",
                                     "Your computer's local time.")
        self.sched_time.insert(0, soon.strftime("%H:%M"))

        bar = self._actions(p, 3)
        self.sched_arm_btn = ctk.CTkButton(
            bar, text="Arm", height=40, width=160, font=(UI_FONT, 13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._arm)
        self.sched_arm_btn.pack(side="left")
        self.sched_disarm_btn = ctk.CTkButton(
            bar, text="Disarm", height=40, width=110, fg_color=NEUTRAL,
            hover_color=NEUTRAL_HOVER, state="disabled",
            command=self._disarm)
        self.sched_disarm_btn.pack(side="left", padx=8)
        ctk.CTkButton(bar, text="← Back to the migration", height=40,
                      width=180, fg_color="transparent",
                      hover_color=CARD_ELEVATED, text_color=TEXT_MUTED,
                      font=(UI_FONT, 12),
                      command=self._back_to_flow).pack(side="right")

        self.sched_state = _Banner(p)
        self.sched_state.grid(row=4, column=0, sticky="ew", pady=(6, 12))
        self.sched_state.show("Not armed.", icon="○", colour=TEXT_MUTED)
        return p

    def _arm(self):
        try:
            when = parse_schedule(self.sched_date.get(), self.sched_time.get())
        except ValueError as e:
            messagebox.showwarning("Check the date and time", str(e))
            return
        if not self._plan:
            messagebox.showwarning(
                "Match first",
                "Run step 2 so the scheduled run has a checked plan — and "
                "so you know how many agents it will move.")
            self._show("match" if self._map_data else "map")
            return
        if not messagebox.askyesno(
                "Arm the scheduler",
                f"At {when:%Y-%m-%d %H:%M} this will move "
                f"{self._plan.get('agents', 0)} agent(s) for real.\n\n"
                f"Keep the app open and the machine awake until then. "
                f"Continue?"):
            return

        self._sched_when = when
        self.sched_arm_btn.configure(state="disabled")
        self.sched_disarm_btn.configure(state="normal")
        cli_log(f"Agent migration scheduled for {when:%Y-%m-%d %H:%M}.",
                "info")
        self._tick()

    def _disarm(self):
        self._cancel_schedule()
        self.sched_state.show("Not armed.", icon="○", colour=TEXT_MUTED)
        self._sched_badge.configure(text="")
        cli_log("Scheduled agent migration cancelled.", "warning")

    def _cancel_schedule(self):
        if self._sched_job is not None:
            try:
                self.after_cancel(self._sched_job)
            except Exception:
                pass
        self._sched_job = None
        self._sched_when = None
        self.sched_arm_btn.configure(state="normal")
        self.sched_disarm_btn.configure(state="disabled")

    def _tick(self):
        if self._sched_when is None:
            return
        remaining = self._sched_when - datetime.now()
        if remaining.total_seconds() <= 0:
            self._cancel_schedule()
            self.sched_state.show("Running now — see step 3.", icon="▶",
                                  colour=ACCENT)
            self._sched_badge.configure(text="")
            cli_log("Scheduled agent migration firing now.", "cmd")
            self._show("live")
            self._run_live(scheduled=True)
            return
        left = format_countdown(remaining)
        self.sched_state.show(
            f"Armed — migrating in {left}  "
            f"({self._sched_when:%Y-%m-%d %H:%M})", icon="⏱", colour=ACCENT)
        self._sched_badge.configure(text=f"⏱ {left}")
        self._sched_job = self.after(1000, self._tick)

    def on_show(self):
        self._refresh_chips()


class _NameFixDialog(ctk.CTkToplevel):
    """Point each unmatched SOURCE scope at its destination counterpart.

    The map entry is renamed to the source's spelling, which is what makes
    the next run match it — exactly the manual rename the standalone tool
    prompted for, but for every mismatch at once and without guessing.
    """

    SKIP = "— leave unmatched —"

    def __init__(self, parent, unmatched, map_data, map_path, on_done):
        super().__init__(parent)
        self.title("Fix name mismatches")
        self.geometry("760x520")
        self._map_data = map_data
        self._map_path = map_path
        self._on_done = on_done
        self._choices = []

        ctk.CTkLabel(
            self, justify="left", wraplength=700, font=(UI_FONT, 12),
            text="Each row is a SOURCE scope with no same-named entry in the "
                 "map file. Pick the destination scope it corresponds to; the "
                 "map file is rewritten to use the source's name.").pack(
            anchor="w", padx=16, pady=(14, 8))

        body = ctk.CTkScrollableFrame(self, fg_color=CARD)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        body.grid_columnconfigure(2, weight=1)

        seen = set()
        row = 0
        for item in unmatched:
            key = (item["kind"], norm_name(item["name"]), item["path"])
            if key in seen:
                continue
            seen.add(key)
            ctk.CTkLabel(body, text=item["kind"], width=64,
                         font=(UI_FONT, 11, "bold"),
                         text_color=TEXT_MUTED).grid(
                row=row, column=0, padx=(8, 4), pady=5, sticky="w")
            ctk.CTkLabel(body, text=f"{item['name']}",
                         font=(UI_FONT, 12)).grid(
                row=row, column=1, padx=4, pady=5, sticky="w")
            options = [self.SKIP] + sorted(
                c for c in item.get("candidates") or [] if c)
            menu = ctk.CTkOptionMenu(body, values=options, width=260,
                                     fg_color=NEUTRAL,
                                     button_color=NEUTRAL_HOVER)
            menu.set(self.SKIP)
            menu.grid(row=row, column=2, padx=8, pady=5, sticky="e")
            self._choices.append((item, menu))
            row += 1
        if not row:
            ctk.CTkLabel(body, text="Nothing to fix.").grid(row=0, column=0)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btns, text="Apply & Save Map", height=34,
                      fg_color=GREEN, hover_color=GREEN_HOVER,
                      font=(UI_FONT, 13, "bold"),
                      command=self._apply).pack(side="right", padx=4)
        ctk.CTkButton(btns, text="Cancel", height=34, fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER,
                      command=self.destroy).pack(side="right", padx=4)

        self.transient(parent)
        self.after(120, self.lift)
        self.grab_set()

    def _apply(self):
        renamed = 0
        for item, menu in self._choices:
            chosen = menu.get()
            if chosen == self.SKIP or not chosen:
                continue
            if rename_in_map(self._map_data, item["kind"], chosen,
                             item["name"]):
                renamed += 1
                cli_log(f"Map: {item['kind']} '{chosen}' → '{item['name']}'",
                        "info")
        if not renamed:
            self.destroy()
            return
        try:
            with open(self._map_path, "w", encoding="utf-8") as f:
                json.dump(self._map_data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Could not save map", str(e), parent=self)
            return
        self.destroy()
        self._on_done(self._map_data, self._map_path, renamed)
