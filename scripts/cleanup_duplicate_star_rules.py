#!/usr/bin/env python3
"""Clean up duplicate STAR (custom detection) rules created at SITE scope.

Background
----------
S1 Command Center before v2.1.8 restored STAR / custom-detection rules without
filtering by the rule's own scope. Because ``GET /cloud-detection/rules``
returns *inherited* rules at every level, an account-scoped rule was captured
and then re-created at the account AND at every child site — so a single
account rule showed up once per site on the destination console.

This script finds those extra SITE-scoped copies (a site-scoped rule whose
``accountId`` + ``name`` [+ ``description`` + ``s1ql``] matches an
account/global-scoped rule) and deletes them via the bulk Delete Rules API
(``DELETE /cloud-detection/rules`` with ``{"filter": {"ids": [...]}}``).

It is **DRY-RUN by default** — it prints what it *would* delete and changes
nothing. Pass ``--delete`` (and confirm, or add ``--yes``) to actually remove
them. The genuine account/global rule is always kept.

Two selection modes
-------------------
``--mode duplicates`` (default)
    Only site-scoped rules that duplicate an account/tenant rule.

``--mode all-site-scoped``
    EVERY site-scoped rule at one named site, whether or not a matching
    parent rule still exists. This is the cleanup for a site that was
    migrated by a pre-2.1.9 build and had the whole tenant's global ruleset
    copied down into it. It requires ``--site-name`` or ``--site-id`` — it
    will refuse to run tenant-wide.

Connection
----------
Reuses a saved S1 Command Center connection from
``~/.s1-command-center/contexts.json`` (by ``--role``, ``--name`` or ``--url``),
or pass ``--url`` and ``--token`` directly.

Examples
--------
    # preview extras on the saved DESTINATION connection
    python scripts/cleanup_duplicate_star_rules.py --role destination

    # actually delete them (asks for confirmation first)
    python scripts/cleanup_duplicate_star_rules.py --role destination --delete

    # limit to one account, no prompt, explicit creds
    python scripts/cleanup_duplicate_star_rules.py \\
        --url mycompany.sentinelone.net --token XXXXXXXX \\
        --account-id 123456789 --delete --yes
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from s1_api import S1API, S1APIError  # noqa: E402


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


def _sig(rule, name_only, wildcard=False):
    """Duplicate signature. accountId is normally included so two different
    accounts that happen to share a rule name are never conflated. Tenant
    (global) rules carry no accountId of their own, so they are indexed and
    looked up under a wildcard account key instead."""
    aid = "" if wildcard else str(rule.get("accountId") or "")
    if name_only:
        return (aid, rule.get("name"))
    return (aid, rule.get("name"), rule.get("description"), rule.get("s1ql"))


def gather_rules(api, account_id=None):
    """Return a de-duplicated list of every STAR rule visible to the token.

    Querying with ``accountIds`` returns the account's own rules plus all of
    its descendant site/group rules, each carrying its own ``scope`` field."""
    if account_id:
        scopes = [{"accountIds": [account_id]}]
    else:
        try:
            accounts = api.get_accounts()
        except S1APIError as exc:
            sys.exit(f"Could not list accounts: {exc}")
        scopes = [{"accountIds": [a.get("id")]} for a in accounts]

    by_id = {}
    for scope in scopes:
        for rule in api.get_star_rules(scope):
            by_id[str(rule.get("id"))] = rule
    return list(by_id.values())


def _norm(value) -> str:
    return " ".join(str(value or "").casefold().split())


def filter_to_site(rules, site_name=None, site_id=None):
    """Rules belonging to one site, matched on siteId or siteName."""
    want = _norm(site_name)
    out = []
    for r in rules:
        if site_id and str(r.get("siteId") or "") == str(site_id):
            out.append(r)
        elif want and _norm(r.get("siteName")) == want:
            out.append(r)
    return out


def find_site_scoped(rules):
    """Every rule that lives at SITE scope (used by --mode all-site-scoped)."""
    return [r for r in (rules or [])
            if str(r.get("scope", "")).lower() == "site"]


def find_extras(rules, name_only=False):
    """Site-scoped rules that duplicate an account- or tenant-scoped rule.

    Account parents are matched within the same accountId. Tenant/global
    parents have no accountId, so they are matched against any account."""
    parents = {}
    for r in rules:
        sc = str(r.get("scope", "")).lower()
        if sc == "account":
            parents.setdefault(_sig(r, name_only), r)
        elif sc in ("global", "tenant"):
            parents.setdefault(_sig(r, name_only, wildcard=True), r)
    extras = []
    for r in rules:
        if str(r.get("scope", "")).lower() != "site":
            continue
        if _sig(r, name_only) in parents \
                or _sig(r, name_only, wildcard=True) in parents:
            extras.append(r)
    return extras


def main():
    ap = argparse.ArgumentParser(
        description="Delete duplicate site-scoped STAR rules created by a "
                    "pre-2.1.8 restore.")
    src = ap.add_argument_group("connection")
    src.add_argument("--role", choices=["source", "destination"],
                     help="Use the saved connection with this role.")
    src.add_argument("--name", help="Use the saved connection with this name.")
    src.add_argument("--url", help="Console URL (or short subdomain). With "
                                    "--token, bypasses saved connections.")
    src.add_argument("--token", help="API token (use with --url).")
    src.add_argument("--ignore-ssl", action="store_true",
                     help="Do not verify TLS certificates.")
    ap.add_argument("--account-id",
                    help="Limit to a single account ID (default: all accounts "
                         "the token can see).")
    ap.add_argument("--site-name",
                    help="Limit to the site with this name (e.g. TR-Servers).")
    ap.add_argument("--site-id", help="Limit to this site ID.")
    ap.add_argument("--mode", choices=["duplicates", "all-site-scoped"],
                    default="duplicates",
                    help="'duplicates' (default) removes only site copies of "
                         "an account/tenant rule. 'all-site-scoped' removes "
                         "EVERY site-scoped rule at the named site — requires "
                         "--site-name/--site-id.")
    ap.add_argument("--match-name-only", action="store_true",
                    help="Treat a site rule as a duplicate on NAME alone "
                         "(default also requires matching description + query).")
    ap.add_argument("--out", metavar="PATH",
                    help="Write the matched rules to a JSON file (audit trail "
                         "for change control). Written in dry-run too.")
    ap.add_argument("--delete", action="store_true",
                    help="Actually delete. Without this it is a dry run.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the confirmation prompt (with --delete).")
    args = ap.parse_args()

    if args.mode == "all-site-scoped" and not (args.site_name or args.site_id):
        ap.error("--mode all-site-scoped requires --site-name or --site-id; "
                 "refusing to select every site-scoped rule in the tenant.")

    base_url, token, verify = _resolve_connection(args)
    api = S1API(base_url, token, verify_ssl=verify)
    try:
        api.get_my_user()
    except Exception as exc:
        sys.exit(f"Cannot reach console {base_url}: {exc}")

    print(f"Connected to {base_url}")
    rules = gather_rules(api, args.account_id)
    print(f"Fetched {len(rules)} STAR rule(s).")

    targeted = None
    if args.site_name or args.site_id:
        targeted = filter_to_site(rules, args.site_name, args.site_id)
        label = args.site_name or args.site_id
        print(f"{len(targeted)} rule(s) belong to site {label!r}.")

    if args.mode == "all-site-scoped":
        extras = find_site_scoped(targeted or [])
        what = f"site-scoped rule(s) at {args.site_name or args.site_id!r}"
    else:
        extras = find_extras(rules, name_only=args.match_name_only)
        if targeted is not None:
            keep = {str(r.get("id")) for r in targeted}
            extras = [r for r in extras if str(r.get("id")) in keep]
        what = ("duplicate site-scoped rule(s) "
                "(an account/global rule of the same name exists)")

    if not extras:
        print("Nothing matched. Nothing to do.")
        return

    print(f"\nFound {len(extras)} {what}:\n")
    for r in extras:
        print(f"  [{r.get('id')}] {r.get('name')!r:40} "
              f"scope={r.get('scope')} site={r.get('scopeName') or r.get('siteName')}")

    if args.out:
        fields = ("id", "name", "description", "scope", "scopeName",
                  "accountId", "accountName", "siteId", "siteName")
        payload = {
            "console": base_url,
            "generated": datetime.now(timezone.utc).isoformat(),
            "match": "name" if args.match_name_only
                     else "name+description+query",
            "total_rules_scanned": len(rules),
            "candidates": [{k: r.get(k) for k in fields} for r in extras],
        }
        with open(args.out, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote audit list ({len(extras)} rule(s)) to {args.out}")

    if not args.delete:
        print("\nDRY RUN — nothing deleted. Re-run with --delete to remove "
              "these rules.")
        return

    if not args.yes:
        if args.mode == "all-site-scoped":
            print("\n!! all-site-scoped mode: this removes EVERY site-scoped "
                  "rule listed above, including any the site legitimately "
                  "owns. Review the list (or --out file) first.")
        ans = input(f"\nDelete these {len(extras)} rule(s)? This cannot be "
                    f"undone. Type 'yes' to proceed: ").strip().lower()
        if ans != "yes":
            print("Aborted.")
            return

    ids = [str(r.get("id")) for r in extras]
    deleted = 0
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        try:
            api.delete_star_rules(batch)
            deleted += len(batch)
            print(f"Deleted {deleted}/{len(ids)}…")
        except S1APIError as exc:
            print(f"  ! Batch starting at {i} failed: {exc}", file=sys.stderr)
    print(f"Done. Deleted {deleted} duplicate rule(s).")


if __name__ == "__main__":
    main()
