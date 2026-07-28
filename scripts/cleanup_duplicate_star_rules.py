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
import os
import sys

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


def _sig(rule, name_only):
    """Duplicate signature. accountId is always included so two different
    accounts that happen to share a rule name are never conflated."""
    aid = str(rule.get("accountId") or "")
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


def find_extras(rules, name_only=False):
    """Site-scoped rules that duplicate an account/global rule (same account)."""
    parents = {}
    for r in rules:
        sc = str(r.get("scope", "")).lower()
        if sc in ("account", "global", "tenant"):
            parents.setdefault(_sig(r, name_only), r)
    extras = []
    for r in rules:
        if str(r.get("scope", "")).lower() == "site" \
                and _sig(r, name_only) in parents:
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
    ap.add_argument("--match-name-only", action="store_true",
                    help="Treat a site rule as a duplicate on NAME alone "
                         "(default also requires matching description + query).")
    ap.add_argument("--delete", action="store_true",
                    help="Actually delete. Without this it is a dry run.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the confirmation prompt (with --delete).")
    args = ap.parse_args()

    base_url, token, verify = _resolve_connection(args)
    api = S1API(base_url, token, verify_ssl=verify)
    try:
        api.get_my_user()
    except Exception as exc:
        sys.exit(f"Cannot reach console {base_url}: {exc}")

    print(f"Connected to {base_url}")
    rules = gather_rules(api, args.account_id)
    print(f"Fetched {len(rules)} STAR rule(s).")

    extras = find_extras(rules, name_only=args.match_name_only)
    if not extras:
        print("No duplicate site-scoped rules found. Nothing to do.")
        return

    print(f"\nFound {len(extras)} duplicate site-scoped rule(s) "
          f"(an account/global rule of the same name exists):\n")
    for r in extras:
        print(f"  [{r.get('id')}] {r.get('name')!r:40} "
              f"scope={r.get('scope')} site={r.get('scopeName') or r.get('siteName')}")

    if not args.delete:
        print("\nDRY RUN — nothing deleted. Re-run with --delete to remove "
              "these rules.")
        return

    if not args.yes:
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
