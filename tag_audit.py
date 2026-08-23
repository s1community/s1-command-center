"""Tag audit — what tags does a console *actually* hold?

Why this exists
---------------
A restore report can only tell you what the API accepted. In the v2.2.0
beijerrefab migration the report showed ~150 endpoint tags created with no
errors, yet the destination console appeared to have none. There are only
three possible explanations, and this module distinguishes them:

1. The tags are there, at the scope we asked for  → the audit lists them.
2. The tags are there at the WRONG scope          → the audit finds them only
   in the tenant-wide sweep, not under the site they were created for.
3. The tags were never stored                     → the audit finds nothing
   and :func:`probe_endpoint_tag_shapes` proves the create is a silent no-op.

Two different APIs back the word "tag" in SentinelOne, and the audit reads
both:

* ``GET /tags?type=<t>`` — named tag objects for firewall,
  network-quarantine and device-inventory (Ranger). These carry a ``name``
  and a ``scope``, and the route returns *inherited* tags at every level, so
  the audit separates a scope's own tags from the ones it merely inherits.
* ``GET /agents/tags`` — unified endpoint tags (Tag Manager), key/value pairs
  created through ``POST /tag-manager``.

Everything here is read-only except :func:`probe_endpoint_tag_shapes`, which
writes throwaway tags and deletes them again.
"""
import json
import unicodedata

from s1_api import S1APIError, created_something, ENDPOINT_TAG_TYPE

TAG_TYPES = ("firewall", "network-quarantine", "device-inventory")

# Routes a console might list unified endpoint tags under. `/agents/tags` is
# the documented one; the rest are cheap to try and a 404 just skips them.
# A probe that only asks one route can't tell "never stored" from "stored
# where we didn't look", and those need completely different fixes.
ENDPOINT_TAG_ROUTES = ("/agents/tags", "/tag-manager")

# Field names seen holding a tag's key across API versions.
KEY_FIELDS = ("key", "tagName", "name")


def norm_name(value) -> str:
    """Case/whitespace/zero-width-insensitive name key (mirrors the GUI)."""
    txt = unicodedata.normalize("NFKC", str(value or ""))
    txt = "".join(ch for ch in txt if ch.isprintable())
    return " ".join(txt.split()).strip().lower()


def name_matches(name, wanted) -> bool:
    """Does `name` satisfy the user's filter? Blank filter matches all."""
    if not wanted:
        return True
    a, b = norm_name(name), norm_name(wanted)
    return a == b or b in a


def scope_filter(ntype: str, node_id: str) -> dict:
    """Query params selecting one scope level."""
    if ntype == "global":
        return {"tenant": "true"}
    return {{"account": "accountIds",
             "site": "siteIds",
             "group": "groupIds"}[ntype]: [node_id]}


def tag_label(tag: dict) -> str:
    """Named tags have `name`; endpoint tags are key/value pairs."""
    if tag.get("name"):
        return str(tag["name"])
    key, val = tag.get("key") or "", tag.get("value") or ""
    return f"{key}={val}" if val else str(key)


def enumerate_scopes(api, account_name: str = "", site_name: str = "",
                     include_groups: bool = False) -> list[tuple]:
    """[(ntype, id, path)] for the tenant and every matching account/site.

    Raises S1APIError if the account list itself can't be read — without it
    there is nothing to audit and a partial answer would be misleading.
    """
    scopes: list[tuple] = [("global", "", "(tenant)")]
    accounts = api.get_accounts() or []

    for acct in accounts:
        aname = acct.get("name", "")
        if not name_matches(aname, account_name):
            continue
        aid = str(acct.get("id"))
        # A site filter means the user is asking about sites, so the account
        # scope itself is noise.
        if not site_name:
            scopes.append(("account", aid, aname))
        try:
            sites = api.get_sites(params={"accountIds": aid}) or []
        except S1APIError:
            sites = []
        for site in sites:
            sname = site.get("name", "")
            if not name_matches(sname, site_name):
                continue
            sid = str(site.get("id"))
            scopes.append(("site", sid, f"{aname}/{sname}"))
            if not include_groups:
                continue
            try:
                groups = api.get_groups(params={"siteIds": sid}) or []
            except S1APIError:
                groups = []
            for grp in groups:
                scopes.append(("group", str(grp.get("id")),
                               f"{aname}/{sname}/{grp.get('name', '')}"))
    return scopes


def _split_own(api, params: dict, level: str, visible: list) -> tuple:
    """Split tags visible at a scope into (own, inherited).

    `scope=<level>` asks the API for only this level's tags; if the console
    doesn't support it we fall back to the tag's own `scope` field, and if
    that is missing too every visible tag counts as owned rather than
    silently disappearing from the audit.
    """
    try:
        own = api.get_all("/tags", params={**params, "scope": level}) or []
        own_ids = {t.get("id") for t in own if t.get("id")}
        inherited = [t for t in visible if t.get("id") not in own_ids] \
            if own_ids else [t for t in visible if t not in own]
        return own, inherited
    except S1APIError:
        pass

    wanted = {"global", "tenant"} if level == "global" else {level}
    own, inherited = [], []
    for tag in visible:
        scope = str(tag.get("scope", "")).lower()
        (own if not scope or scope in wanted else inherited).append(tag)
    return own, inherited


def read_scope(api, ntype: str, node_id: str) -> dict:
    """Every tag object visible at one scope, split own vs inherited.

    Errors are collected per tag type instead of raised: a token missing one
    permission shouldn't blank out the tag types it *can* read.
    """
    scope = scope_filter(ntype, node_id)
    level = "global" if ntype == "global" else ntype
    out = {"named": {}, "endpoint": [], "endpoint_route": "", "errors": {}}

    for ttype in TAG_TYPES:
        params = dict(scope)
        params["type"] = ttype
        try:
            visible = api.get_all("/tags", params=params) or []
        except S1APIError as exc:
            out["errors"][ttype] = str(exc)
            continue
        own, inherited = _split_own(api, params, level, visible)
        out["named"][ttype] = {"own": own, "inherited": inherited}

    first_error = ""
    for route in ENDPOINT_TAG_ROUTES:
        try:
            found = api.get_all(route, params=dict(scope)) or []
        except S1APIError as exc:
            first_error = first_error or str(exc)
            continue
        out["endpoint_route"] = out["endpoint_route"] or route
        if found:
            out["endpoint"] = found
            out["endpoint_route"] = route
            break
    if not out["endpoint_route"] and first_error:
        out["errors"]["endpoint"] = first_error
    return out


def scope_rows(ntype: str, path: str, found: dict,
               include_inherited: bool = False,
               tag_type: str = "all") -> list[dict]:
    """Flatten one scope's findings into table/report rows."""
    rows: list[dict] = []
    for ttype in TAG_TYPES:
        if tag_type not in ("all", ttype):
            continue
        info = found["named"].get(ttype)
        if not info:
            continue
        for tag in info["own"]:
            rows.append({"scope": path, "level": ntype, "type": ttype,
                         "tag": tag_label(tag), "owned": "own",
                         "id": tag.get("id", "")})
        if include_inherited:
            for tag in info["inherited"]:
                rows.append({"scope": path, "level": ntype, "type": ttype,
                             "tag": tag_label(tag), "owned": "inherited",
                             "id": tag.get("id", "")})
    if tag_type in ("all", "endpoint"):
        for tag in found["endpoint"]:
            rows.append({"scope": path, "level": ntype, "type": "endpoint",
                         "tag": tag_label(tag), "owned": "own",
                         "id": tag.get("id", "")})
    return rows


# ── endpoint-tag write probe ───────────────────────────────────────────
# The tag object is settled — {"type": "agents", "key": …, "value": …}, all
# three required, and the type is what GET /agents/tags reports. The envelope
# around it is what this probe is for: these are the shapes POST /tag-manager
# is known to answer 200 to, and only one of them actually stores a tag.
PROBE_SHAPES = (
    ("data object + filter  (what the restore sends)",
     lambda tag, scope: {"data": tag, "filter": scope}),
    ("data array + filter",
     lambda tag, scope: {"data": [tag], "filter": scope}),
    ("data.tags array + filter",
     lambda tag, scope: {"data": {"tags": [tag]}, "filter": scope}),
    ("data object, no filter",
     lambda tag, scope: {"data": tag}),
    ("bare tag object",
     lambda tag, scope: dict(tag)),
)

NO_SHAPE_WORKED = (
    "No request shape produced a tag this tool can read back, on any known "
    "listing route. Either the console discards the write, or it stores the "
    "tag somewhere these routes don't show. Look for keys starting "
    "'s1cc-probe-' in the console's own tag list: if they are there, the "
    "write works and the listing route is wrong — send a screenshot. If they "
    "are not, check the token's 'Tag Management' create permission and "
    "whether the route is enabled for this tenant.")

CLAIMED_BUT_UNREADABLE = (
    "The console reported creating a tag, but no listing route can see it "
    "afterwards. The write probably worked and this tool is reading the "
    "wrong route — which would also explain an audit that shows no endpoint "
    "tags. Check the console's tag list for keys starting 's1cc-probe-' and "
    "delete them by hand: they could not be cleaned up automatically because "
    "they could not be found.")


def _key_matches(tag: dict, key: str) -> bool:
    wanted = key.strip().lower()
    return any(str(tag.get(f) or "").strip().lower() == wanted
               for f in KEY_FIELDS)


def find_endpoint_tag(api, key: str, scope: dict) -> tuple:
    """Look for one tag by key on every route and filter a console might
    list it under. Returns (matches, where, at_scope) — `where` names what
    found it, `at_scope` is False when only the tenant-wide read saw it.
    """
    seen: list = []
    for route in ENDPOINT_TAG_ROUTES:
        attempts = [(dict(scope), True)]
        if scope.get("tenant") != "true":
            attempts.append(({"tenant": "true"}, False))
        for params, at_scope in attempts:
            if (route, tuple(sorted(params))) in seen:
                continue
            seen.append((route, tuple(sorted(params))))
            try:
                found = [t for t in (api.get_all(route, params=params) or [])
                         if _key_matches(t, key)]
            except S1APIError:
                continue
            if found:
                where = (f"GET {route}" if at_scope
                         else f"GET {route} (tenant-wide)")
                return found, where, at_scope
    return [], "", False


def _trim(resp) -> str:
    """The console's own words, short enough to log."""
    try:
        text = json.dumps(resp, default=str)
    except (TypeError, ValueError):
        text = str(resp)
    return text if len(text) <= 300 else text[:300] + "…"


def probe_endpoint_tag_shapes(api, ntype: str, node_id: str, stamp: str,
                              log=lambda *_: None) -> dict:
    """WRITES. Find out which POST /tag-manager body the console stores.

    Each candidate body is sent with its own throwaway key, then proven by
    reading it back — a 2xx is not evidence. What the console *said* is kept
    alongside what could be found, because "it claimed a create and nothing
    is readable" means the listing route is wrong, while "it claimed nothing
    and nothing is readable" means the write was discarded. Anything that
    does appear is deleted again. `stamp` makes the throwaway keys
    identifiable; the caller supplies it so this stays deterministic.

    Returns {winner, found_via, wrong_scope, unreadable, results[],
    leftovers[], probe_keys[]}.
    """
    scope = scope_filter(ntype, node_id)
    out = {"winner": None, "found_via": "", "wrong_scope": False,
           "unreadable": False, "results": [], "leftovers": [],
           "probe_keys": []}
    leftovers: list = []

    for idx, (label, build) in enumerate(PROBE_SHAPES, 1):
        key = f"s1cc-probe-{stamp}-{idx}"
        tag = {"type": ENDPOINT_TAG_TYPE, "key": key, "value": "probe"}
        result = {"shape": label, "outcome": "", "detail": "",
                  "response": "", "found_via": "", "key": key}
        out["probe_keys"].append(key)
        try:
            resp = api._post("/tag-manager", body=build(tag, scope))
        except S1APIError as exc:
            result["outcome"] = "rejected"
            result["detail"] = str(exc)
            out["results"].append(result)
            log(f"   [{idx}] {label} — rejected: {exc}")
            continue

        result["response"] = _trim(resp)
        claimed = created_something(resp)
        log(f"   [{idx}] {label} — console answered: {result['response']}")

        found, where, at_scope = find_endpoint_tag(api, key, scope)
        result["found_via"] = where
        if found and at_scope:
            result["outcome"] = "stored"
            out["winner"] = out["winner"] or label
            out["found_via"] = out["found_via"] or where
            log(f"       STORED, visible at this {ntype} scope via {where}")
        elif found:
            result["outcome"] = "wrong-scope"
            out["wrong_scope"] = True
            out["winner"] = out["winner"] or f"{label} [wrong scope]"
            out["found_via"] = out["found_via"] or where
            log(f"       stored, but NOT at the requested scope — only "
                f"{where} sees it, so the filter was ignored")
        elif claimed:
            result["outcome"] = "claimed-unreadable"
            out["unreadable"] = True
            log(f"       the console claims it created something, but no "
                f"listing route can find '{key}' — the tag may exist where "
                f"this tool isn't looking")
        else:
            result["outcome"] = "no-op"
            log(f"       accepted, claimed nothing, and nothing is "
                f"readable: no-op")
        out["results"].append(result)
        leftovers += [t.get("id") for t in found if t.get("id")]

    for tag_id in dict.fromkeys(leftovers):
        if not delete_endpoint_tag(api, tag_id):
            out["leftovers"].append(tag_id)
            log(f"   ⚠ could not delete probe tag {tag_id} — remove it by "
                f"hand (key starts with 's1cc-probe-{stamp}')")
        else:
            log(f"   ✓ cleaned up probe tag {tag_id}")
    return out


def delete_endpoint_tag(api, tag_id: str) -> bool:
    """Delete one endpoint tag. True if the console accepted a delete."""
    for body in ({"data": {"ids": [tag_id]}}, {"filter": {"ids": [tag_id]}}):
        try:
            api._request("DELETE", "/tag-manager", body=body)
            return True
        except S1APIError:
            continue
    return False
