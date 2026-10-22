"""Compare a backup with the console it is about to be restored onto.

The restore finds accounts, sites and groups on the destination by their
EXACT name: a backup scope with a twin there is restored into it, and one
without is created from the backup file. `RestoreComparison` shows that
before anything is written — the backup's account › site › group tree,
each scope beside what the destination has in the same place, and why —
and holds the renames the operator picks so a backup scope lands in the
destination scope it really is. Nothing here writes to a console: the
renames change the loaded backup, the same way Rename in the backup does.

Everything above the window is plain Python, testable without a display.
"""
import difflib
from concurrent.futures import ThreadPoolExecutor

from agent_migrator import (_NameFixDialog, _col, _grid_shown, _plural,
                            _retext, _short)
from app import (ACCENT, BRAND, GREEN, INFO, TEXT_FAINT, TEXT_MUTED, WARN,
                 run_async)
from pages import _node_scope_names, _norm_name

KINDS = ("account", "site", "group")
INACTIVE = ("expired", "deleted", "disabled")
RESTORE_STATES = ("near", "new", "blocked", "chosen", "waiting", "create",
                  "same")
RESTORE_FILTERS = {"all": None,
                   "fix": ("near", "new", "blocked", "chosen", "waiting"),
                   "done": ("chosen",)}
RENAMABLE = ("near", "new", "create", "chosen", "blocked")
READ_WORKERS = 6
_LEVEL = {"account": "Accounts", "site": "Sites", "group": "Groups"}
_BELOW = {"account": "sites and groups", "site": "groups", "group": ""}
_SLASH = ("A name with “/” can't be used: the backup keeps its scopes in "
          "account/site/group paths.")


# ── reading the destination (worker thread) ────────────────────────────

def _active(sites):
    return [s for s in sites or []
            if str(s.get("state") or "active").lower() not in INACTIVE]


def read_account(api, account) -> list:
    """One destination account's active sites, each with its groups — what
    the restore looks a backup site and its groups up in:
    [{"id", "name", "isDefault", "groups": [{"id", "name"}]}]."""
    sites = _active(api.get_sites(params={"accountIds": account["id"]}))

    def groups(site):
        return [{"id": str(g.get("id") or ""), "name": str(g.get("name") or "")}
                for g in api.get_groups(params={"siteIds": site.get("id")})
                or []]

    with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        found = list(pool.map(groups, sites))
    return [{"id": str(s.get("id") or ""), "name": str(s.get("name") or ""),
             "isDefault": bool(s.get("isDefault")), "groups": g}
            for s, g in zip(sites, found)]


def backup_accounts(backup, indices) -> list:
    """The account names — as the restore reads them — of the nodes in
    `indices`, in backup order. Empty when the restore only touches global
    settings."""
    out = []
    for i in indices:
        node = backup[i]
        if node.get("type") in KINDS:
            name = _node_scope_names(node)[0]
            if name and name not in out:
                out.append(name)
    return out


def read_destination(api, names, account_id="") -> dict:
    """What the destination holds for a restore of the backup accounts
    `names`, read once:

      accounts - every active account the token sees: [{"id", "name"}]
      held     - {name: state} for a backup account whose exact name an
                 expired or deleted account still holds
      sites    - {account id: read_account()} for every account a backup
                 account can land in: the same name, the same name in
                 another case or spacing, or the ticket's account ID
    """
    accounts = [{"id": str(a.get("id")), "name": str(a.get("name") or "")}
                for a in api.get_accounts() or [] if a.get("id")]
    exact = {a["name"] for a in accounts}
    near = {}
    for a in accounts:
        near.setdefault(_norm_name(a["name"]), []).append(a)
    wanted, missing = {}, []
    for name in names:
        if name not in exact:
            missing.append(name)
        for a in near.get(_norm_name(name), []):
            wanted[a["id"]] = a
    ticket = str(account_id or "").strip()
    hit = next((a for a in accounts if ticket and a["id"] == ticket), None)
    if hit:
        wanted[hit["id"]] = hit

    def holder(name):
        try:
            rows = api.get_accounts_any_state(name=name) or []
        except Exception:
            return name, ""          # can't tell — the restore will say
        for row in rows:
            state = str(row.get("state") or "").lower()
            if row.get("name") == name and state not in ("", "active"):
                return name, state
        return name, ""

    with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        held = dict(h for h in pool.map(holder, missing) if h[1])
    return {"accounts": accounts, "held": held,
            "sites": {aid: read_account(api, a) for aid, a in wanted.items()}}


# ── the comparison ─────────────────────────────────────────────────────

class RestoreComparison:
    """The backup's account › site › group tree beside the destination.

    Built from the loaded backup, the restore's scope and one destination
    read, so drawing and filtering it costs no call. It holds every scope
    the restore touches plus the scopes above them, and decides each one
    the way the restore will:

      same    - the destination has it by exact name: restored into it
      near    - there in another case or spacing, which the exact-name
                restore misses
      new     - not there, though its place holds others: created
      create  - not there, and nothing there to match it with: created
      chosen  - renamed here — to an existing scope, or a new name
      blocked - not restored at all, and nor is anything under it
      waiting - its destination account is still being read

    A rename is a pick, not an edit: `renames()` lists them for
    `rename_in_backup`, and the backup only changes when they are applied.
    """

    def __init__(self, backup, indices, dest, account_id="", items=None):
        self.accounts = list(dest.get("accounts") or [])
        self.held = dict(dest.get("held") or {})
        self.sites = dict(dest.get("sites") or {})
        self.errors = {}
        self.choices, self._typed, self._memo = {}, set(), {}
        self._exact = {}
        for a in self.accounts:
            self._exact.setdefault(a["name"], a)    # the restore takes the first
        self.account_id = str(account_id or "").strip()
        self._by_id = next((a for a in self.accounts
                            if self.account_id and a["id"] == self.account_id),
                           None)
        self.id_missing = bool(self.account_id) and self._by_id is None
        self._build(backup, set(indices), items)

    def _build(self, backup, scope, items):
        full, roots = {}, []
        for i, node in enumerate(backup):
            kind = node.get("type")
            if kind not in KINDS:
                continue
            names = tuple(_node_scope_names(node)[:KINDS.index(kind) + 1])
            if not all(names):
                continue
            for depth in range(len(names)):
                key = names[:depth + 1]
                if key in full:
                    continue
                full[key] = {"name": key[-1], "kind": KINDS[depth],
                             "path": list(key), "parent": key[:-1] or None,
                             "children": [], "idx": [], "restores": False,
                             "items": 0, "default": False}
                (full[key[:-1]]["children"] if depth else roots).append(key)
            entry = full[names]
            entry["idx"].append(i)
            if kind == "site" and (node.get("site") or {}).get("isDefault"):
                entry["default"] = True
            if i in scope:
                entry["restores"] = True
                entry["items"] += int(items(node) or 0) if items else 0
        keep = {}

        def visit(key):
            shown = [k for k in full[key]["children"] if visit(k)]
            keep[key] = full[key]["restores"] or bool(shown)
            return keep[key]

        for root in roots:
            visit(root)
        self.full, self._all_roots = full, roots
        self.nodes = {k: dict(n, children=[c for c in n["children"] if keep[c]])
                      for k, n in full.items() if keep[k]}
        self.roots = [k for k in roots if keep[k]]

    # ── what the restore will do with each scope ──────────────────────

    def name_for(self, key) -> str:
        """The name it is restored under: the rename, or the backup's."""
        return self.choices.get(key) or self.full[key]["name"]

    def _resolve(self, key):
        """(state, destination entry or None, what its children find) —
        "exists", "unread", "failed", "created" or "absent"."""
        hit = self._memo.get(key)
        if hit is None:
            hit = self._memo[key] = self._decide(key)
        return hit

    def _decide(self, key):
        node = self.full[key]
        kind, name = node["kind"], self.name_for(key)
        restores, chosen = node["restores"], key in self.choices
        if kind == "account":
            if self._by_id is not None:
                entry = self._by_id
                state = (("chosen" if chosen else "same")
                         if entry["name"] == name else "near")
                return state, entry, self._read_state(entry)
            pool = self.accounts
        else:
            if kind == "group" and self._groups_lost(key):
                return "blocked", None, "absent"
            _state, up, fate = self._resolve(node["parent"])
            if fate in ("unread", "failed"):
                return "waiting", None, fate
            if fate == "absent" or (fate == "created" and not restores):
                return "blocked", None, "absent"
            if fate == "created":
                return ("chosen" if chosen else "create"), None, "created"
            pool = self._inside(node["parent"], up)
        hit = next((e for e in pool if e["name"] == name), None)
        if hit is not None:
            return (("chosen" if chosen else "same"), hit,
                    self._read_state(hit) if kind == "account" else "exists")
        if kind == "account" and self.held.get(name):
            return "blocked", None, "absent"
        made = "created" if restores else "absent"
        if chosen:
            return "chosen", None, made
        if any(_norm_name(e["name"]) == _norm_name(name) for e in pool):
            return "near", None, made
        if not restores:
            return "blocked", None, "absent"
        return ("new" if pool else "create"), None, "created"

    def _read_state(self, account):
        if self.sites.get(account["id"]) is not None:
            return "exists"
        return "failed" if account["id"] in self.errors else "unread"

    def _inside(self, parent, entry) -> list:
        """What the destination scope `entry` (where `parent` lands) holds."""
        if self.full[parent]["kind"] == "account":
            return self.sites.get(entry["id"]) or []
        return entry.get("groups") or []

    def _groups_lost(self, key) -> bool:
        """Groups look their account up by NAME — the ticket's account ID
        only steers accounts and sites — so under an account that is on the
        destination only by that ID, its groups find nothing."""
        return (self._by_id is not None
                and self.name_for(key[:1]) not in self._exact)

    def state(self, key) -> str:
        return self._resolve(key)[0]

    def entry(self, key):
        """The destination scope this one is restored into, or None."""
        return self._resolve(key)[1]

    def fate(self, key) -> str:
        return self._resolve(key)[2]

    def where(self, key) -> str:
        """The place this scope is looked for in, in words."""
        parent = self.full[key]["parent"]
        if parent is None:
            return "the destination"
        kind, entry = self.full[parent]["kind"], self.entry(parent)
        if entry is not None:
            return f"the destination {kind} “{entry['name']}”"
        if self.fate(parent) == "created":
            return f"the new {kind} “{self.name_for(parent)}”"
        return f"the {kind} “{self.name_for(parent)}”"

    def has_place(self, key) -> bool:
        """Its place exists on the destination, so there is a list to pick
        from."""
        parent = self.full[key]["parent"]
        return parent is None or self.fate(parent) == "exists"

    def can_rename(self, key) -> bool:
        """A rename of this scope changes what the restore does with it."""
        node = self.full[key]
        if node["kind"] == "group" and self._groups_lost(key):
            return False
        return (node["parent"] is None
                or self.fate(node["parent"]) in ("exists", "created"))

    def fix_at(self, key):
        """The scope above this one to fix first, or None."""
        if self.full[key]["kind"] == "group" and self._groups_lost(key):
            return key[:1]
        top, parent = None, self.full[key]["parent"]
        while parent is not None:
            if self.fate(parent) in ("absent", "unread", "failed"):
                top = parent
            parent = self.full[parent]["parent"]
        return top

    def _twin(self, key) -> str:
        """The destination scope with this name in another case/spacing."""
        parent = self.full[key]["parent"]
        if parent is None:
            pool = self.accounts
        elif self.fate(parent) == "exists":
            pool = self._inside(parent, self.entry(parent))
        else:
            pool = []
        want = _norm_name(self.name_for(key))
        return next((e["name"] for e in pool
                     if _norm_name(e["name"]) == want), "")

    def _dest_name(self, key) -> str:
        entry = self.entry(key)
        return (entry["name"] if entry is not None
                else self.choices.get(key) or self._twin(key))

    # ── the destination scopes a backup scope could go into ───────────

    def _siblings(self, key):
        """Backup scopes sharing this one's place, by normalised name:
        ({name: (backup name, in this restore)} for those keeping their
        name, {name: backup name} for those renamed to it)."""
        parent = self.full[key]["parent"]
        keys = self._all_roots if parent is None else self.full[parent]["children"]
        held, picked = {}, {}
        for k in keys:
            if k == key:
                continue
            if k in self.choices:
                picked.setdefault(_norm_name(self.choices[k]),
                                  self.full[k]["name"])
            else:
                held.setdefault(_norm_name(self.full[k]["name"]),
                                (self.full[k]["name"], k in self.nodes))
        return held, picked

    def candidates(self, key) -> list:
        """The destination scopes in this scope's place, closest name first,
        each with the backup scope already restoring into it."""
        node = self.full[key]
        parent = node["parent"]
        if parent is None:
            pool = [self._by_id] if self._by_id is not None else self.accounts
        elif self.fate(parent) == "exists":
            pool = self._inside(parent, self.entry(parent))
        else:
            return []
        held, picked = self._siblings(key)
        out, seen = [], set()
        for e in pool:
            n = _norm_name(e["name"])
            if not n or e["name"] in seen or "/" in e["name"]:
                continue
            seen.add(e["name"])
            taken = held.get(n)
            out.append({"name": e["name"], "shown": e["name"],
                        "taken_by": taken[0] if taken else "",
                        "scoped": bool(taken and taken[1]),
                        "chosen_for": picked.get(n, ""),
                        "default": bool(e.get("isDefault"))})
        target = _norm_name(node["name"])

        def closeness(c):
            other = _norm_name(c["shown"])
            score = difflib.SequenceMatcher(None, target, other).ratio()
            return score + (0.5 if other and (other in target
                                              or target in other) else 0)

        out.sort(key=lambda c: (bool(c["taken_by"] or c["chosen_for"]),
                                -closeness(c), c["shown"].casefold()))
        return out

    def check(self, key, name) -> tuple:
        """("free" | "taken" | "self" | "bad" | "unknown", detail) for
        renaming this scope to `name`: the destination's exact name when
        free, the backup scope already using it when taken."""
        value = " ".join(str(name or "").split())
        if "/" in value:
            return "bad", _SLASH
        if value == self.full[key]["name"]:
            return "self", ""
        wanted = _norm_name(value)
        for c in self.candidates(key):
            if _norm_name(c["name"]) == wanted:
                holder = c["taken_by"] or c["chosen_for"]
                return ("taken", holder) if holder else ("free", c["name"])
        held, picked = self._siblings(key)
        if wanted in held:
            return "taken", held[wanted][0]
        if wanted in picked:
            return "taken", picked[wanted]
        return "unknown", ""

    def elsewhere(self, key) -> list:
        """Where else the destination (as read) has a scope of this name."""
        node = self.full[key]
        if node["kind"] == "account":
            return []
        name, here = _norm_name(node["name"]), self.entry(node["parent"])
        label = {a["id"]: a["name"] for a in self.accounts}
        found = []
        for account_id, sites in self.sites.items():
            for site in sites or []:
                if node["kind"] == "site":
                    if (here is None or account_id != here["id"]) and \
                            _norm_name(site["name"]) == name:
                        found.append(label.get(account_id, account_id))
                elif site is not here and any(
                        _norm_name(g["name"]) == name
                        for g in site.get("groups") or []):
                    found.append(f"{label.get(account_id, account_id)} › "
                                 f"{site['name']}")
        return found

    # ── renames ───────────────────────────────────────────────────────

    def choose(self, key, name, allow_unknown=False) -> bool:
        """Rename a backup scope: to the destination scope `name` in its
        place, or — with `allow_unknown` — to a new name it is created
        under. False when another backup scope already uses that name
        there, or the rename would change nothing."""
        if (key not in self.nodes or self.state(key) not in RENAMABLE
                or not self.can_rename(key)):
            return False
        value = " ".join(str(name or "").split())
        verdict, detail = self.check(key, value)
        if not value or verdict in ("taken", "self", "bad"):
            return False
        if verdict == "free":
            value = detail
        elif not allow_unknown:
            return False
        if self.choices.get(key) != value:
            self._forget_below(key)
        self.choices[key] = value
        (self._typed.add if verdict == "unknown" else self._typed.discard)(key)
        self._memo.clear()
        return True

    def unchoose(self, key):
        self._forget_below(key)
        self.choices.pop(key, None)
        self._typed.discard(key)
        self._memo.clear()

    def _forget_below(self, key):
        """A parent's rename decides what its children are compared with."""
        for child in self.full[key]["children"]:
            self._forget_below(child)
            self.choices.pop(child, None)
            self._typed.discard(child)

    def typed(self, key) -> bool:
        return key in self._typed

    def renames(self) -> list:
        """The renames, parents first, for `rename_in_backup`:
        [{"kind", "path": [backup names down to it], "new"}]."""
        picks = sorted(self.choices.items(), key=lambda kv: (len(kv[0]), kv[0]))
        return [{"kind": self.full[k]["kind"], "path": list(k), "new": v}
                for k, v in picks]

    # ── destination accounts read later ───────────────────────────────

    def unread(self) -> list:
        """Destination accounts a rename points at but nobody has read."""
        out = {}
        for key in self.roots:
            entry = self.entry(key)
            if entry is not None and self.fate(key) == "unread":
                out[entry["id"]] = entry
        return list(out.values())

    def add_account(self, account_id, sites=None, error=None):
        """One more destination account read — or the reason it wasn't."""
        if error is not None:
            self.errors[account_id] = str(error) or "the read failed"
        else:
            self.sites[account_id] = list(sites or [])
            self.errors.pop(account_id, None)
        self._memo.clear()

    # ── what to show ──────────────────────────────────────────────────

    @property
    def dest_empty(self) -> bool:
        """The destination has no account at all to restore into."""
        return not self.accounts

    @property
    def nothing_there(self) -> bool:
        """No scope of this restore is on the destination in any form."""
        return not any(self.entry(k) is not None or self.state(k) == "near"
                       for k in self.nodes)

    def created(self) -> dict:
        """{kind: count} of scopes this restore creates."""
        out = dict.fromkeys(KINDS, 0)
        for key, node in self.nodes.items():
            if node["restores"] and self.fate(key) == "created":
                out[node["kind"]] += 1
        return out

    def items_text(self, key) -> str:
        node = self.full[key]
        return f"{node['items']:,}" if node["restores"] else "—"

    def summary(self) -> dict:
        counts = dict.fromkeys(RESTORE_STATES, 0)
        for key in self.nodes:
            counts[self.state(key)] += 1
        return counts

    def visible(self, filt="all", query="", collapsed=()) -> list:
        """(key, depth) in display order: what the filter keeps, the scopes
        above it for context, and — while searching — everything under a
        match, folded or not."""
        wanted, q = RESTORE_FILTERS.get(filt), _norm_name(query)

        def walk(key, inherited):
            node = self.nodes[key]
            hit = (inherited or not q or q in _norm_name(node["name"])
                   or q in _norm_name(self._dest_name(key)))
            below = [row for child in node["children"]
                     for row in walk(child, hit and bool(q))]
            keep = hit and (wanted is None or self.state(key) in wanted)
            if not keep and not below:
                return []
            row = [(key, len(key) - 1)]
            return row if key in collapsed and not q else row + below

        return [row for root in self.roots for row in walk(root, False)]

    def dest_text(self, key) -> str:
        """What the tree shows in its destination column."""
        state, entry, fate = self._resolve(key)
        kind = self.full[key]["kind"]
        if state == "same":
            return "✓ exists"
        if state == "near":
            if kind == "account" and self._by_id is not None:
                return f"≈ “{entry['name']}” · by ticket ID"
            return f"≈ “{self._twin(key)}” · other case"
        if state == "chosen":
            pick = self.choices[key]
            if entry is not None:
                return f"→ “{pick}”"
            return f"→ “{pick}” · " + ("new name" if fate == "created"
                                       else "skipped")
        if state == "waiting":
            return "· couldn't read" if fate == "failed" else "· reading…"
        if state == "blocked":
            held = self.held.get(self.name_for(key)) if kind == "account" else ""
            return f"✕ name held ({held})" if held else "✕ skipped"
        return "+ will be created"

    def reason(self, key) -> str:
        """Why this scope is restored into something, created or skipped."""
        node = self.full[key]
        kind, name, parent = node["kind"], self.name_for(key), node["parent"]
        state, entry, fate = self._resolve(key)
        place = self.where(key)
        lead = place[:1].upper() + place[1:]
        art = "an" if kind == "account" else "a"
        below, level = _BELOW[kind], _LEVEL[kind]
        if state == "waiting":
            account = self.entry(key[:1])
            label = f"“{account['name']}”" if account else "its account"
            if fate == "failed":
                why = self.errors.get(account["id"], "") if account else ""
                return (f"Couldn't read the destination account {label}: "
                        f"{why} — compare again to retry.")
            return f"Reading what the destination account {label} holds…"
        if kind == "account" and self._by_id is not None:
            text = (f"The ticket's account ID ({self.account_id}) sends this "
                    f"account and its sites to “{entry['name']}”, whatever "
                    f"their name.")
            if entry["name"] != name:
                text += (f" Its groups look the account up by name, though — "
                         f"rename it to “{entry['name']}” so they land there "
                         f"too.")
            return text
        if state == "same":
            if node["restores"]:
                return (f"{lead} has {art} {kind} named “{name}”: the restore "
                        f"finds it by name and restores the backup's settings "
                        f"into it.")
            return (f"{lead} has {art} {kind} named “{name}”. It isn't "
                    f"restored itself — {level} isn't ticked in step 2 — but "
                    f"its {below} restore into it.")
        if state == "chosen":
            pick = self.choices[key]
            if entry is not None:
                text = (f"Renamed to “{pick}” in the backup, so the restore "
                        f"finds the existing {kind} in {place} and restores "
                        f"into it.")
            elif fate == "created":
                text = (f"Renamed to “{pick}”. {lead} has no {kind} of that "
                        f"name, so the restore creates it under the new name.")
            else:
                text = (f"Renamed to “{pick}”, but {place} has no {kind} of "
                        f"that name and this restore doesn't create it, so "
                        f"its {below} are skipped.")
            return text + " The backup changes when you apply."
        if state == "near":
            twin = self._twin(key)
            text = (f"{lead} has “{twin}” — the same name in another case or "
                    f"spacing. The restore matches names exactly, so ")
            text += (f"it would try to create “{name}” beside it, and the "
                     f"console may refuse the near-duplicate name."
                     if node["restores"] else
                     f"it won't find it, and its {below} are skipped.")
            return (text + f" Rename it to “{twin}” to restore into the "
                           f"existing {kind}.")
        if state == "blocked":
            return self._blocked_reason(key, name, lead, below, level)
        if state == "create":
            if parent is None:
                return (f"The destination has no accounts yet, so the restore "
                        f"creates “{name}” from the backup file.")
            if self.fate(parent) == "created":
                up = self.full[parent]["kind"]
                text = (f"Its {up} is created by this restore too, so “{name}” "
                        f"is created inside it from the backup file.")
                if kind == "site":
                    text += (" A new account starts with a default site of "
                             "its own: the restore may ask whether to restore "
                             "this site onto it or create it new.")
                return text
            return (f"{lead} has no {kind}s yet, so the restore creates "
                    f"“{name}” from the backup file.")
        cands = self.candidates(key)
        free = sum(1 for c in cands if not (c["taken_by"] or c["chosen_for"]))
        text = (f"{lead} has no {kind} named “{name}”, so the restore creates "
                f"it from the backup file. It has {_plural(len(cands), kind)}")
        text += (f" — {free:,} with nothing restoring into it. If “{name}” is "
                 f"one of them under another name, pick it below." if free
                 else f", each with a backup {kind} restoring into it.")
        if kind == "site":
            text += self._site_question(key)
        return text

    def _blocked_reason(self, key, name, lead, below, level) -> str:
        node = self.full[key]
        kind, parent = node["kind"], node["parent"]
        held = self.held.get(name) if kind == "account" else ""
        if held:
            return (f"An account named “{name}” already exists on the "
                    f"destination, but it is {held}: the restore can't restore "
                    f"into it or reuse the name. Rename it to an active "
                    f"account here, or reactivate that account on the "
                    f"destination.")
        if kind == "group" and self._groups_lost(key):
            return (f"Groups look their account up by name, and the ticket's "
                    f"account ID only steers accounts and sites. Rename the "
                    f"account “{self.full[key[:1]]['name']}” to "
                    f"“{self._by_id['name']}” so this group restores too.")
        if parent is not None and self.fate(parent) == "absent":
            up = self.full[parent]["kind"]
            return (f"Its {up} “{self.name_for(parent)}” won't be on the "
                    f"destination, so this {kind} is skipped too. Fix the "
                    f"{up} first.")
        why = (f"{level} isn't ticked in step 2" if node["idx"] else
               f"the backup holds no {kind} record for it — it was backed up "
               f"without {level}")
        return (f"{lead} has no {kind} named “{name}”, and this restore "
                f"doesn't create it ({why}), so its {below} are skipped. "
                f"Rename it to an existing {kind}, or tick {level} in step 2.")

    def _site_question(self, key) -> str:
        """What the restore asks when it reaches a site its account lacks —
        the same choice `RestorePage._resolve_dest_id` offers."""
        parent = self.full[key]["parent"]
        sites = self._inside(parent, self.entry(parent))
        held = {c["name"]: c["taken_by"] or c["chosen_for"]
                for c in self.candidates(key)}

        def warn(site):
            who = held.get(site["name"])
            return (f" Answer No there: “{site['name']}” is where the backup "
                    f"site “{who}” restores." if who else "")

        if self.full[key]["default"]:
            spot = next((s for s in sites
                         if s["name"].lower() == "default site"), None)
            if spot:
                return (f" Because it is the backup's default site, the "
                        f"restore asks whether to restore it over "
                        f"“{spot['name']}” (renaming that site) — unattended "
                        f"restores do." + warn(spot))
        spare = (next((s for s in sites if s["isDefault"]), None)
                 or (sites[0] if len(sites) == 1 else None))
        if not spare:
            return ""
        text = (f" When the restore reaches it, it asks whether to put it on "
                f"“{spare['name']}” instead (renaming that site) or create it "
                f"new — unattended restores create it new.")
        if warn(spare):
            return text + warn(spare)
        if spare["name"] in held:
            text += (f" Pick “{spare['name']}” here to restore into it and "
                     f"keep its name.")
        return text


def describe(cmp, console="destination") -> tuple:
    """(line, tone) for the restore screen: what a comparison found. Tone
    is "info", "warn" or "ok"."""
    s = cmp.summary()
    made = ", ".join(_plural(n, k) for k, n in cmp.created().items() if n)
    tail = f": {made}." if made else "."
    if cmp.dest_empty:
        return (f"The {console} console has no accounts yet — this restore "
                f"will create everything from the backup file{tail}", "info")
    if cmp.nothing_there:
        return (f"Nothing in this restore is on the {console} console yet — "
                f"it will create all of it from the backup file{tail}", "info")
    bits = [f"{s['same']:,} exist",
            f"{s['new'] + s['create']:,} will be created"]
    if s["near"]:
        bits.append(f"{s['near']:,} near match"
                    + ("es" if s["near"] != 1 else ""))
    if s["blocked"]:
        bits.append(f"{s['blocked']:,} skipped")
    return (f"Compared with {console}: " + " · ".join(bits) + ".",
            "warn" if s["near"] or s["blocked"] else "ok")


def rename_in_backup(backup, renames) -> list:
    """Apply `RestoreComparison.renames()` to the loaded backup the way
    Rename in the backup does: every node under a renamed scope gets the
    new name in its path, and the renamed node itself in its own record.
    Parents go first, so a site under a renamed account is found by the
    account's new name. Returns [{"kind", "from", "to", "count"}] with
    "Account/Site/Group" paths."""
    applied, done = {}, []
    for item in sorted(renames, key=lambda r: len(r["path"])):
        orig, new = tuple(item["path"]), item["new"]
        current = tuple(applied.get(orig[:d + 1], orig[d])
                        for d in range(len(orig)))
        depth, count = len(orig) - 1, 0
        for node in backup:
            kind = node.get("type")
            if kind not in KINDS or KINDS.index(kind) < depth:
                continue
            names = list(_node_scope_names(node)[:KINDS.index(kind) + 1])
            if tuple(names[:len(current)]) != current:
                continue
            names[depth] = new
            if KINDS.index(kind) == depth:
                own = node.get(kind)
                if not isinstance(own, dict):
                    own = node[kind] = {}
                own["name"] = new
            node["path"] = ("/".join(names) + "/" if kind == "account"
                            else "/".join(names))
            count += 1
        applied[orig] = new
        done.append({"kind": item["kind"], "from": "/".join(current),
                     "to": "/".join(current[:-1] + (new,)), "count": count})
    return done


# ── the window ─────────────────────────────────────────────────────────

class RestoreCompareDialog(_NameFixDialog):
    """The backup beside the destination, before anything is restored.

    Left: what the restore touches — account › site › group — and what
    each lands in: ✓ an existing scope, + created from the backup file,
    ≈ the same name in another case, ✕ skipped. Right: why, every
    destination scope in that place and the backup scope already restoring
    into it, and the rename. Nothing is sent: Apply renames the scopes in
    the loaded backup, and the restore screen takes it from there.
    """

    TITLE = "Compare with the destination — backup vs destination"
    FILTERS = {"Needs a look": "fix", "All": "all", "Renamed": "done"}
    MARK = {"same": "✓", "near": "≈", "new": "+", "create": "+",
            "chosen": "→", "blocked": "✕", "waiting": "·"}
    TONE = {"same": GREEN, "near": WARN, "new": INFO, "create": TEXT_MUTED,
            "chosen": BRAND, "blocked": ACCENT, "waiting": TEXT_FAINT}
    LOUD = ("near", "new", "chosen", "blocked")
    COLUMNS = [_col("In the backup", "_name", 5),
               _col("", "_kind", 0, minsize=58),
               _col("Items", "_agents", 0, anchor="e", mono=True, minsize=56),
               _col("On the destination", "_dest", 6)]
    EMPTY = "Nothing in this restore sits in an account, site or group."
    ATTENTION = ("near", "blocked", "new")
    COLLAPSE = ()
    PICKABLE = RENAMABLE
    OTHER = ("waiting",)
    UNFIX = ()
    SEARCH_HINT = "Search backup or destination names…"
    CAND_HINT = "Filter — or type a new name for it"
    CAND_HEADS = ("Destination", "Already restored from")
    CAND_EMPTY = "Nothing here on the destination yet."
    USE_IDLE = "Restore into selected"
    CLEAR_TEXT = "Undo rename"
    FOOTNOTE = ("Renames change the loaded backup, not the file on disk — "
                "and nothing is sent to the console.")
    APPLY_IDLE = "Apply renames"

    def __init__(self, parent, comparison, on_done, loader=None,
                 console="destination"):
        self._acct_loader = loader
        self._console_name = console
        self._reading_ids = set()
        super().__init__(parent, comparison, on_done)
        self._read_unread()

    def _intro(self):
        cmp, where = self.cmp, self._console_name
        made = ", ".join(_plural(n, k) for k, n in cmp.created().items() if n)
        made = f" — {made}" if made else ""
        if cmp.dest_empty:
            return (f"The {where} console has no accounts yet, so there is "
                    f"nothing to compare with: the restore will create "
                    f"everything below from the backup file{made}. You can "
                    f"still rename anything before it is created.", INFO)
        if cmp.nothing_there:
            return (f"Nothing in this restore is on the {where} console yet: "
                    f"the restore will create all of it from the backup "
                    f"file{made}. If a scope belongs in one the destination "
                    f"already has, select it and pick that one.", INFO)
        text = ("What this restore touches — account › site › group — beside "
                "what the destination has in the same place. The restore "
                "finds scopes by exact name: ✓ is restored into the existing "
                "scope, + is created from the backup file, ≈ is there in "
                "another case or spacing, ✕ is skipped. Select a scope to see "
                "why, and rename it to match an existing one where it should. "
                "Nothing is sent — renames change the loaded backup when you "
                "apply them.")
        if cmp.id_missing:
            text += (f" The ticket's account ID ({cmp.account_id}) isn't on "
                     f"this console, so names decide.")
        return text, TEXT_MUTED

    # ── counts ────────────────────────────────────────────────────────

    def _count_text(self, key):
        return self.cmp.items_text(key)

    def _count_bits(self):
        s = self.cmp.summary()
        bits = [f"{s['same']:,} exist",
                f"{s['new'] + s['create']:,} will be created"]
        if s["near"]:
            bits.append(f"{s['near']:,} near match"
                        + ("es" if s["near"] != 1 else ""))
        if s["blocked"]:
            bits.append(f"{s['blocked']:,} skipped")
        if s["chosen"]:
            bits.append(f"{s['chosen']:,} renamed")
        if s["waiting"]:
            bits.append(f"{s['waiting']:,} reading")
        return bits

    def _changes(self):
        return len(self.cmp.choices)

    def _apply_text(self, changes):
        return f"Rename {_plural(changes, 'scope')} in the backup"

    def _paint_counts(self):
        super()._paint_counts()
        text, tone = self._intro()
        _retext(self._intro_lbl, text=text, text_color=tone)

    # ── the selected scope ────────────────────────────────────────────

    def _show_detail(self):
        super()._show_detail()
        key, cmp = self._selected, self.cmp
        if key is None:
            return
        state = cmp.state(key)
        stuck = state in self.PICKABLE and not cmp.can_rename(key)
        if stuck:
            _grid_shown(self._pick_box, False)
        up = cmp.fix_at(key)
        goto = up is not None and up in cmp.nodes and (stuck
                                                       or state == "waiting")
        _grid_shown(self._other, goto)
        _grid_shown(self._goto_btn, goto)
        if goto:
            _retext(self._goto_btn, text=f"Show the {cmp.full[up]['kind']}")

    def _goto_parent(self):
        key = self._selected
        if key is None:
            return
        up = self.cmp.fix_at(key) or self.cmp.full[key]["parent"]
        if up is not None and up in self.cmp.nodes:
            self._select(up)

    def _detail_head(self, kind):
        return f"BACKUP {kind.upper()}"

    def _detail_bits(self, key):
        cmp = self.cmp
        node, shown = cmp.full[key], cmp.nodes[key]["children"]
        kind = node["kind"]
        where = " › ".join(node["path"][:-1])
        bits = [f"in {where}" if where else "an account in the backup"]
        if shown:
            bits.append(_plural(len(shown), "group" if kind == "site"
                                else "site"))
        if not node["restores"]:
            bits.append("not restored itself")
        elif node["items"]:
            bits.append(f"{_plural(node['items'], 'item')} in the backup")
        else:
            bits.append("no items of its own")
        return bits

    def _elsewhere_text(self, key, state):
        node = self.cmp.full[key]
        kind = node["kind"]
        seen = self.cmp.elsewhere(key) if state in self.PICKABLE else []
        if not seen:
            return ""
        more = f" and {len(seen) - 5:,} more" if len(seen) > 5 else ""
        return (f"Elsewhere on the destination, a {kind} named "
                f"“{node['name']}” is in "
                + ", ".join(f"“{w}”" for w in seen[:5]) + more
                + f". The restore only looks inside its own "
                  f"{'account' if kind == 'site' else 'site'}.")

    def _cand_title(self, kind):
        key = self._selected
        if key is not None and not self._cands:
            if (self.cmp.state(key) == "blocked"
                    and not self.cmp.full[key]["restores"]):
                return f"No destination {kind} to restore it into"
            return "Rename it before it is created"
        return f"Restore it into an existing destination {kind}"

    def _cand_used(self, c, kind):
        if c["taken_by"]:
            return (f"backup {kind} “{c['taken_by']}”"
                    + ("" if c["scoped"] else " · not in this restore"))
        if c["chosen_for"]:
            return f"your rename of “{c['chosen_for']}”"
        return "nothing yet — free"

    def _use_text(self, pick):
        return f"Restore into “{_short(pick['shown'], 22)}”"

    def _typed_text(self, typed):
        return f"Rename to “{_short(typed, 22)}”"

    def _pick_note(self, key, pick, typed, verdict, holder):
        cmp = self.cmp
        node = cmp.full[key]
        kind, name, place = node["kind"], node["name"], cmp.where(key)
        lead = place[:1].upper() + place[1:]
        if pick and pick["taken_by"]:
            return (f"The backup {kind} “{pick['taken_by']}” already restores "
                    f"into “{pick['shown']}”. Renaming “{name}” to it as well "
                    f"would merge the two in the backup. Pick another, or "
                    f"leave this one to be created.", ACCENT)
        if pick and pick["chosen_for"]:
            return (f"“{pick['shown']}” is already your rename for "
                    f"“{pick['chosen_for']}” — two backup {kind}s can't share "
                    f"one name.", ACCENT)
        if pick:
            return (f"“{name}” will be renamed to “{pick['shown']}” in the "
                    f"backup, so the restore finds the existing {kind} by name "
                    f"and restores into it. The destination itself isn't "
                    f"changed.", GREEN)
        if verdict == "bad":
            return holder, ACCENT
        if verdict == "self":
            return f"“{typed}” is its name in the backup already.", TEXT_MUTED
        if verdict == "unknown":
            if cmp.has_place(key):
                return (f"{lead} has no {kind} named “{typed}”: the restore "
                        f"will create it under that name instead of "
                        f"“{name}”.", INFO)
            return f"“{name}” will be created as “{typed}”.", INFO
        if verdict == "taken":
            return (f"The backup {kind} “{holder}” already uses that name "
                    f"here — two backup {kind}s can't share one name.", ACCENT)
        if verdict == "free":
            return (f"“{holder}” is in {place} — select it in the list to "
                    f"restore into it.", GREEN)
        if not self._cands and cmp.state(key) == "blocked":
            if not node["restores"]:
                return (f"{lead} has nothing to restore it into, and this "
                        f"restore doesn't create {kind}s — tick "
                        f"{_LEVEL[kind]} in step 2.", WARN)
            return (f"Type a new name above — the restore creates the {kind} "
                    f"under that name instead.", TEXT_MUTED)
        if not self._cands:
            if cmp.has_place(key):
                return (f"{lead} has no {kind}s, so “{name}” is created there. "
                        f"Type a name above to create it under another one.",
                        TEXT_MUTED)
            return (f"“{name}” is created inside {place}. Type a name above "
                    f"to create it under another one.", TEXT_MUTED)
        spare = sum(1 for c in self._cands
                    if not (c["taken_by"] or c["chosen_for"]))
        return (f"{_plural(len(self._cands), kind)} in {place} · {spare:,} "
                f"free. Closest names first; grey ones already have a backup "
                f"{kind} restoring into them. Or type a new name to create it "
                f"under.", TEXT_MUTED)

    # ── renames, and destination accounts read on demand ──────────────

    def _changed(self, advance=False):
        super()._changed(advance)
        self._read_unread()

    def _read_unread(self):
        """A rename can point a backup account at a destination account
        nobody has read yet: read its sites and groups in the background."""
        if self._acct_loader is None:
            return
        for account in self.cmp.unread():
            if account["id"] in self._reading_ids:
                continue
            self._reading_ids.add(account["id"])
            run_async(self.master, lambda a=account: self._acct_loader(a),
                      lambda sites, a=account: self._account_read(a, sites),
                      lambda exc, a=account: self._account_read(a, None, exc))

    def _account_read(self, account, sites, error=None):
        self._reading_ids.discard(account["id"])
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return              # the window closed while it was reading
        self.cmp.add_account(account["id"], sites, error=error)
        self._refresh()
        self._show_detail()

    def _apply(self):
        renames = self.cmp.renames()
        self.destroy()
        if renames:
            self._on_done(renames)
