#!/usr/bin/env python3
"""Audit every tag object a console actually holds — ground truth for
"the restore said it created tags but they aren't there".

Why this exists
---------------
A restore report can only tell you what the API *accepted*. In the beijerrefab
migration (v2.2.0, 2026-08-13) the report showed ~150 endpoint tags created
with no errors, yet the destination console appeared to have none. There are
only three possible explanations, and this script distinguishes them:

1. The tags are there, at the scope we asked for   → audit shows them per scope.
2. The tags are there, but at the WRONG scope      → audit shows them only in
   the tenant-wide sweep, not under the site/account they were created for.
3. The tags were never persisted                   → audit shows nothing
   anywhere, and ``--probe`` proves the create call is a silent no-op.

What it reads
-------------
Two different APIs back the word "tag" in SentinelOne:

* ``GET /tags?type=<t>``  — named tag objects for **firewall**,
  **network-quarantine** and **device-inventory** (Ranger). These have a
  ``name`` and a ``scope``, and the endpoint returns *inherited* tags at every
  level, so the audit also asks for ``scope=<level>`` to separate a scope's
  OWN tags from the ones it merely inherits.
* ``GET /agents/tags`` — unified **endpoint tags** (Tag Manager), which are
  key/value pairs created through ``POST /tag-manager``.

Everything here is READ-ONLY unless you pass ``--probe``.

Examples
--------
    # what does the destination console actually hold?
    python scripts/audit_tags.py --role destination

    # compare source vs destination, one account, machine-readable
    python scripts/audit_tags.py --role source      --json src.json
    python scripts/audit_tags.py --role destination --json dst.json

    # only one account, and include group scopes
    python scripts/audit_tags.py --role destination \\
        --account-name beijerrefab --groups

    # WRITES: create a throwaway endpoint tag at one site, check whether it
    # becomes visible, then delete it again
    python scripts/audit_tags.py --role destination --site-name US --probe
"""
import argparse
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from s1_api import S1API, S1APIError  # noqa: E402

TAG_TYPES = ("firewall", "network-quarantine", "device-inventory")


def _resolve_connection(args):
    """Return (base_url, token, verify_ssl) from CLI args or saved config."""
    if args.url and args.token:
        url = args.url
        if not url.startswith("http"):
            url = url if "." in url else f"{url}.sentinelone.net"
            url = f"https://{url}"
        return url.rstrip("/"), args.token, not args.ignore_ssl

    try:
        from config import ConfigManager
    except Exception as exc:  # pragma: no cover - defensive
        sys.exit(f"Could not load saved connections: {exc}")

    cfg = ConfigManager()
    ctx = None
    if args.url:
        ctx = cfg.get_by_url(args.url) or next(
            (c for c in cfg.contexts if args.url in c.url), None)
    if not ctx and args.name:
        ctx = next((c for c in cfg.contexts if c.name == args.name), None)
    if not ctx and args.role:
        ctx = cfg.get_by_role(args.role)
    if not ctx:
        avail = ", ".join(f"{c.name} [{c.role or 'no-role'}] {c.display_url}"
                          for c in cfg.contexts) or "(none saved)"
        sys.exit("No matching saved connection. Use --url/--token, or one of "
                 f"--role/--name matching: {avail}")
    return ctx.url.rstrip("/"), ctx.api_token, not ctx.ignore_ssl_errors


def _norm(value: str) -> str:
    """Case/'whitespace/zero-width-insensitive name key (mirrors the GUI)."""
    txt = unicodedata.normalize("NFKC", str(value or ""))
    txt = "".join(ch for ch in txt if ch.isprintable())
    return " ".join(txt.split()).strip().lower()


def _matches(name: str, wanted: str) -> bool:
    if not wanted:
        return True
    a, b = _norm(name), _norm(wanted)
    return a == b or b in a


def _scope_filter(ntype: str, node_id: str) -> dict:
    if ntype == "global":
        return {"tenant": "true"}
    return {{"account": "accountIds",
             "site": "siteIds",
             "group": "groupIds"}[ntype]: [node_id]}


def _tag_label(tag: dict) -> str:
    """Named tags have `name`; endpoint tags are key/value pairs."""
    if tag.get("name"):
        return str(tag["name"])
    key, val = tag.get("key") or "", tag.get("value") or ""
    return f"{key}={val}" if val else str(key)


def enumerate_scopes(api, args):
    """[(ntype, id, path)] for the tenant and every account/site (+groups)."""
    scopes = [("global", "", "(tenant)")]
    try:
        accounts = api.get_accounts() or []
    except S1APIError as exc:
        sys.exit(f"Could not list accounts: {exc}")

    for acct in accounts:
        aname = acct.get("name", "")
        if not _matches(aname, args.account_name):
            continue
        aid = str(acct.get("id"))
        if not args.site_name:
            scopes.append(("account", aid, aname))
        try:
            sites = api.get_sites(params={"accountIds": aid}) or []
        except S1APIError:
            sites = []
        for site in sites:
            sname = site.get("name", "")
            if not _matches(sname, args.site_name):
                continue
            sid = str(site.get("id"))
            scopes.append(("site", sid, f"{aname}/{sname}"))
            if not args.groups:
                continue
            try:
                groups = api.get_groups(params={"siteIds": sid}) or []
            except S1APIError:
                groups = []
            for grp in groups:
                scopes.append(("group", str(grp.get("id")),
                               f"{aname}/{sname}/{grp.get('name', '')}"))
    return scopes


def read_scope(api, ntype: str, node_id: str) -> dict:
    """Every tag object visible at one scope, split own vs inherited."""
    scope = _scope_filter(ntype, node_id)
    level = "global" if ntype == "global" else ntype
    out = {"named": {}, "endpoint": [], "errors": {}}

    for ttype in TAG_TYPES:
        params = dict(scope)
        params["type"] = ttype
        try:
            visible = api.get_all("/tags", params=params) or []
        except S1APIError as exc:
            out["errors"][ttype] = str(exc)
            continue
        # `scope=<level>` asks the API itself for only this level's tags; fall
        # back to the tag's own `scope` field if the console ignores it.
        try:
            own = api.get_all("/tags", params={**params, "scope": level}) or []
        except S1APIError:
            own = [t for t in visible
                   if str(t.get("scope", "")).lower()
                   in ({"global", "tenant"} if level == "global" else {level})]
        out["named"][ttype] = {
            "own": [_tag_label(t) for t in own],
            "inherited": max(len(visible) - len(own), 0),
            "sample": own[0] if own else (visible[0] if visible else None),
        }

    try:
        eps = api.get_all("/agents/tags", params=dict(scope)) or []
        out["endpoint"] = eps
    except S1APIError as exc:
        out["errors"]["endpoint"] = str(exc)
    return out


# The tag object is documented ({"type": "endpoints", "key": …}); the
# envelope around it is not. These are the shapes POST /tag-manager is known
# to answer 200 to — only one of them actually stores a tag.
PROBE_SHAPES = (
    ("data object + filter  (what v2.2.0 sends)",
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


def _find_probe_tag(api, key, params):
    try:
        return [t for t in (api.get_all("/agents/tags", params=params) or [])
                if t.get("key") == key]
    except S1APIError:
        return []


def probe(api, ntype: str, node_id: str, path: str) -> None:
    """Find out which POST /tag-manager body the console actually stores.

    This is the only part of the script that writes. It answers what a
    read-only audit cannot: the restore reported ~150 endpoint tags created
    with no errors against a console that has none, so either the create is a
    silent no-op or the tag lands somewhere other than the scope we asked
    for. Each candidate body is sent with its own throwaway key, then proven
    by re-reading GET /agents/tags. Anything that does appear is deleted.
    """
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    scope = _scope_filter(ntype, node_id)
    print(f"\n── PROBE: POST /tag-manager at {ntype} '{path}' ──────────────")
    print(f"   {len(PROBE_SHAPES)} throwaway tags will be created and then "
          f"deleted again.\n")

    winner = None
    leftovers = []
    for idx, (label, build) in enumerate(PROBE_SHAPES, 1):
        key = f"s1cc-probe-{stamp}-{idx}"
        tag = {"type": "endpoints", "key": key, "value": "probe"}
        print(f"   [{idx}] {label}")
        try:
            resp = api._post("/tag-manager", body=build(tag, scope))
        except S1APIError as exc:
            print(f"       ✗ rejected: {exc}")
            detail = str(getattr(exc, "detail", ""))[:200]
            if detail:
                print(f"         {detail}")
            continue
        body_txt = json.dumps(resp)[:160] if resp else "(empty)"
        print(f"       → 2xx, response: {body_txt}")

        at_scope = _find_probe_tag(api, key, dict(scope))
        at_tenant = _find_probe_tag(api, key, {"tenant": "true"})
        if at_scope:
            print(f"       ✓ STORED and visible at this {ntype} scope")
            winner = winner or label
        elif at_tenant:
            print("       ⚠ stored, but NOT at the requested scope "
                  "(the filter was ignored)")
            winner = winner or f"{label} [wrong scope]"
        else:
            print("       ✗ accepted but the tag does not exist — no-op")
        leftovers += [t.get("id") for t in (at_scope or at_tenant)
                      if t.get("id")]

    print()
    if winner:
        print(f"   → the console stores endpoint tags sent as: {winner}")
    else:
        print("   → no request shape created a tag: this console takes the "
              "request and discards it. Two things do that — a token without "
              "the 'Tag Management.create' permission, or a tenant where the "
              "route is disabled. Check the token's permissions first.")

    for tag_id in dict.fromkeys(leftovers):
        for body in ({"data": {"ids": [tag_id]}}, {"filter": {"ids": [tag_id]}}):
            try:
                api._request("DELETE", "/tag-manager", body=body)
                print(f"   ✓ cleaned up probe tag {tag_id}")
                break
            except S1APIError:
                continue
        else:
            print(f"   ⚠ could not delete probe tag {tag_id} — remove it by "
                  f"hand (key starts with 's1cc-probe-{stamp}')")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Audit every tag object on a SentinelOne console.")
    conn = ap.add_argument_group("connection")
    conn.add_argument("--url", help="console URL (or a saved connection URL)")
    conn.add_argument("--token", help="API token (with --url)")
    conn.add_argument("--role", choices=["source", "destination"],
                      help="use the saved connection with this role")
    conn.add_argument("--name", help="use the saved connection with this name")
    conn.add_argument("--ignore-ssl", action="store_true",
                      help="skip TLS verification")

    ap.add_argument("--account-name", default="",
                    help="only audit accounts matching this name")
    ap.add_argument("--site-name", default="",
                    help="only audit sites matching this name")
    ap.add_argument("--groups", action="store_true",
                    help="also audit group scopes (slow on big tenants)")
    ap.add_argument("--empty", action="store_true",
                    help="also print scopes that hold no tags at all")
    ap.add_argument("--sample", action="store_true",
                    help="print one raw tag object per type (shows the real "
                         "field names the console returns)")
    ap.add_argument("--json", dest="json_out", metavar="PATH",
                    help="write the full audit to a JSON file")
    ap.add_argument("--probe", action="store_true",
                    help="WRITES: create a throwaway endpoint tag at the "
                         "first audited scope, verify it, then delete it")
    args = ap.parse_args(argv)

    url, token, verify = _resolve_connection(args)
    api = S1API(url, token, verify_ssl=verify)
    try:
        api.get_my_user()
    except Exception as exc:
        sys.exit(f"Could not reach {url}: {exc}")
    print(f"Console: {url}")

    scopes = enumerate_scopes(api, args)
    print(f"Auditing {len(scopes)} scope(s)…\n")

    report = {"console": url,
              "generated": datetime.now(timezone.utc).isoformat(),
              "scopes": []}
    totals = {t: 0 for t in TAG_TYPES}
    totals["endpoint"] = 0
    shown_sample = set()

    for ntype, node_id, path in scopes:
        found = read_scope(api, ntype, node_id)
        named_counts = {t: len(v["own"])
                        for t, v in found["named"].items()}
        ep_count = len(found["endpoint"])
        for t, n in named_counts.items():
            totals[t] += n
        totals["endpoint"] += ep_count

        report["scopes"].append({
            "type": ntype, "id": node_id, "path": path,
            "named": {t: v["own"] for t, v in found["named"].items()},
            "inherited": {t: v["inherited"]
                          for t, v in found["named"].items()},
            "endpointTags": [_tag_label(t) for t in found["endpoint"]],
            "errors": found["errors"],
        })

        if not args.empty and not any(named_counts.values()) \
                and not ep_count and not found["errors"]:
            continue

        print(f"[{ntype.upper():7}] {path}")
        for ttype in TAG_TYPES:
            info = found["named"].get(ttype)
            if not info:
                continue
            if info["own"] or info["inherited"]:
                extra = (f"  (+{info['inherited']} inherited)"
                         if info["inherited"] else "")
                print(f"    {ttype:20} {len(info['own']):4}{extra}")
                for label in info["own"][:10]:
                    print(f"        · {label}")
                if len(info["own"]) > 10:
                    print(f"        · … {len(info['own']) - 10} more")
            if args.sample and info["sample"] and ttype not in shown_sample:
                shown_sample.add(ttype)
                print(f"        raw: {json.dumps(info['sample'])[:400]}")
        if ep_count:
            print(f"    {'endpoint (tag-manager)':20} {ep_count:4}")
            for tag in found["endpoint"][:10]:
                print(f"        · {_tag_label(tag)}")
            if ep_count > 10:
                print(f"        · … {ep_count - 10} more")
            if args.sample and "endpoint" not in shown_sample:
                shown_sample.add("endpoint")
                print(f"        raw: "
                      f"{json.dumps(found['endpoint'][0])[:400]}")
        for what, err in found["errors"].items():
            print(f"    ⚠ {what}: {err}")
        print()

    print("── TOTALS (tags owned by the audited scopes) ──────────────────")
    for ttype in TAG_TYPES:
        print(f"   {ttype:24} {totals[ttype]}")
    print(f"   {'endpoint (tag-manager)':24} {totals['endpoint']}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"\nFull audit written to {args.json_out}")

    if args.probe:
        ntype, node_id, path = next(
            (s for s in scopes if s[0] != "global"), scopes[0])
        probe(api, ntype, node_id, path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
