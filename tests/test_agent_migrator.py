"""Tests for the mapped agent-migration workflow (agent_migrator.py).

The point of this page is that each SOURCE group's agents go to the
SAME-NAMED destination group's registration token — not to one flat site
token. Everything here locks that behaviour down, plus the two failure
modes the standalone tool kept hitting: a scope whose name differs between
the consoles (silently skipped, then silently mis-migrated after a manual
rename), and a run that re-sends agents that already moved.
"""
import ast
import inspect
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_migrator as am  # noqa: E402
from s1_api import S1API, S1APIError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── fakes ───────────────────────────────────────────────────────────────

class FakeAPI:
    """Minimal console: one account, its sites, their groups, their agents."""

    def __init__(self, account, sites, agents=None, fail_moves=False,
                 verify_as="Migrated"):
        self.account = account
        self.sites = sites
        self.agents = agents or {}
        self.moves = []
        self.fail_moves = fail_moves
        self.passphrase_calls = 0
        # what a read-back says about an agent the console accepted
        self.verify_as = verify_as
        self.accepted = set()
        self.id_lookups = []

    # scopes
    def get_account_by_id(self, account_id):
        if str(self.account.get("id")) == str(account_id):
            return dict(self.account)
        return None

    def get_accounts(self, **kw):
        return [dict(self.account)]

    def get_sites(self, params=None, **kw):
        want = (params or {}).get("siteIds")
        out = []
        for s in self.sites:
            if want and str(s["id"]) != str(want):
                continue
            out.append({k: v for k, v in s.items() if k != "groups"})
        return out

    def get_groups(self, params=None, **kw):
        sid = str((params or {}).get("siteIds", ""))
        for s in self.sites:
            if str(s["id"]) == sid:
                return [dict(g) for g in s.get("groups") or []]
        return []

    # agents
    def get_agents(self, params=None, **kw):
        params = dict(params or {})
        if "ids" in params:                      # the post-move read-back
            wanted = str(params["ids"]).split(",")
            self.id_lookups.append(wanted)
            out = []
            for rows in self.agents.values():
                for agent in rows:
                    if str(agent.get("id")) not in wanted:
                        continue
                    rec = dict(agent)
                    if str(agent.get("id")) in self.accepted:
                        rec["consoleMigrationStatus"] = self.verify_as
                    out.append(rec)
            return out
        rows = list(self.agents.get(str(params.get("groupIds", "")), []))
        if params.get("consoleMigrationStatusesNin") == "Migrated":
            rows = [a for a in rows
                    if a.get("consoleMigrationStatus") != "Migrated"]
        return rows

    def move_agents_to_console(self, agent_ids, token, extra_filter=None):
        self.moves.append({"ids": list(agent_ids), "token": token,
                           "filter": dict(extra_filter or {})})
        if self.fail_moves:
            raise RuntimeError("console refused the move")
        self.accepted.update(str(a) for a in agent_ids)
        return {"data": {"affected": len(agent_ids)}}

    def get_agent_passphrase(self, agent_id):
        self.passphrase_calls += 1
        return [{"passphrase": f"pp-{agent_id}"}]


def _dest_console():
    return FakeAPI(
        {"id": "900", "name": "Acme"},
        [{"id": "s1", "name": "HQ", "registrationToken": "tok-hq",
          "groups": [{"id": "g1", "name": "Servers",
                      "registrationToken": "tok-servers"},
                     {"id": "g2", "name": "Laptops",
                      "registrationToken": ""}]},
         {"id": "s2", "name": "Branch", "registrationToken": "tok-branch",
          "groups": [{"id": "g3", "name": "Default Group",
                      "registrationToken": "tok-default"}]}])


def _source_console(**kw):
    agents = {
        "G1": [{"id": "a1", "computerName": "WIN-SRV-01",
                "osName": "Windows Server 2019", "isActive": True},
               {"id": "a2", "computerName": "WIN-SRV-02",
                "osName": "Windows Server 2019", "isActive": False}],
        "G2": [{"id": "b1", "computerName": "MAC-DEV-07",
                "osName": "macOS 14", "isActive": True}],
        "G3": [{"id": "c1", "computerName": "LNX-BUILD-3",
                "osName": "Ubuntu 22.04", "isActive": True}],
    }
    return FakeAPI(
        {"id": "100", "name": "Acme"},
        [{"id": "S1", "name": "HQ",
          "groups": [{"id": "G1", "name": "Servers", "totalAgents": 2},
                     {"id": "G2", "name": "Laptops", "totalAgents": 1},
                     {"id": "G9", "name": "Empty", "totalAgents": 0}]},
         {"id": "S2", "name": "Branch",
          "groups": [{"id": "G3", "name": "Default Group",
                      "totalAgents": 1}]}],
        agents=agents, **kw)


def _map():
    return am.build_scope_map(_dest_console(), "900")


def _plan_for(api, map_data=None, accounts="100", **kw):
    return am.build_match_plan(api, map_data or _map(), accounts, **kw)


def _migrate(api, map_data=None, group=None, verify=False, **kw):
    """Plan, then run — optionally only one group's row."""
    rows = _plan_for(api, map_data, **kw)["rows"]
    if group:
        rows = [r for r in rows if r["Group"] == group]
    return am.run_live_migration(api, rows, verify=verify)


# ── small helpers ───────────────────────────────────────────────────────

def test_console_url_is_reduced_to_the_base_domain():
    assert am.parse_console_url(
        "https://usea1-partners.sentinelone.net/incidents/threats?x=1"
    ) == "https://usea1-partners.sentinelone.net"
    assert am.parse_console_url("  https://x.sentinelone.net/  ") == \
        "https://x.sentinelone.net"
    # anything else is left alone (bar a trailing slash)
    assert am.parse_console_url("https://console.internal/") == \
        "https://console.internal"


def test_batched_never_loses_or_duplicates_items():
    items = list(range(2500))
    chunks = list(am.batched(items, 1000))
    assert [len(c) for c in chunks] == [1000, 1000, 500]
    assert [x for c in chunks for x in c] == items


def test_countdown_is_human_readable():
    assert am.format_countdown(timedelta(seconds=59)) == "00:00:59"
    assert am.format_countdown(timedelta(hours=2, minutes=3)) == "02:03:00"
    assert am.format_countdown(timedelta(days=1, hours=1)) == "1d 01:00:00"
    assert am.format_countdown(timedelta(seconds=-5)) == "00:00:00"


# ── step 1: the destination map ─────────────────────────────────────────

def test_map_records_every_scope_and_its_token():
    data = _map()
    assert am.map_counts(data) == (1, 2, 3)
    hq = data[0]["sites"][0]
    assert hq["name"] == "HQ" and hq["token"] == "tok-hq"
    assert [g["name"] for g in hq["groups"]] == ["Servers", "Laptops"]
    assert hq["groups"][0]["token"] == "tok-servers"


def test_map_refuses_an_account_the_token_cannot_see():
    try:
        am.build_scope_map(_dest_console(), "does-not-exist")
    except ValueError as e:
        assert "not found" in str(e).lower()
        assert "does-not-exist" in str(e)      # names the id it couldn't find
    else:
        raise AssertionError("expected a ValueError")


def test_a_site_nothing_can_move_into_is_flagged_before_the_run():
    data = _map()
    assert am.sites_without_token(data) == []

    # HQ loses its token; "Laptops" has none of its own → stranded.
    data[0]["sites"][0]["token"] = ""
    assert am.sites_without_token(data) == [("Acme", "HQ")]

    # …but a site whose groups all carry their own token is still usable.
    data[0]["sites"][0]["groups"][1]["token"] = "tok-laptops"
    assert am.sites_without_token(data) == []

    # a tokenless site with no groups at all has nowhere to put anything
    data[0]["sites"][0]["groups"] = []
    assert am.sites_without_token(data) == [("Acme", "HQ")]


# ── name matching ───────────────────────────────────────────────────────

def test_names_match_regardless_of_case_and_spacing():
    sites = _map()[0]["sites"]
    assert am.find_by_name(sites, "  hq  ", "site")["id"] == "s1"


def test_a_missing_name_reports_the_candidates_it_could_have_matched():
    sites = _map()[0]["sites"]
    try:
        am.find_by_name(sites, "Head Office", "site")
    except am.MappingError as e:
        assert e.kind == "site" and e.name == "Head Office"
        assert e.candidates == ["HQ", "Branch"]
    else:
        raise AssertionError("expected a MappingError")


def test_a_group_without_a_token_falls_back_to_its_site():
    site = _map()[0]["sites"][0]
    servers, laptops = site["groups"]
    assert am.token_for(servers, site) == "tok-servers"
    assert am.token_for(laptops, site) == "tok-hq"


def test_renaming_the_map_aligns_it_with_the_source():
    data = _map()
    assert am.rename_in_map(data, "site", "HQ", "Head Office") is True
    assert data[0]["sites"][0]["name"] == "Head Office"
    assert am.rename_in_map(data, "group", "Laptops", "Workstations") is True
    assert data[0]["sites"][0]["groups"][1]["name"] == "Workstations"
    assert am.rename_in_map(data, "account", "Acme", "Acme Corp") is True
    assert data[0]["name"] == "Acme Corp"
    assert am.rename_in_map(data, "group", "Nope", "X") is False


# ── step 2: moving the agents ───────────────────────────────────────────

def test_planning_counts_without_sending_anything():
    api = _source_console()
    plan = _plan_for(api)
    assert api.moves == []
    assert [r["Agents"] for r in plan["rows"]] == [2, 1, 1]


def test_a_live_move_carries_the_token_and_skips_already_migrated():
    api = _source_console()
    api.agents["G1"].append({"id": "a3", "computerName": "OLD-01",
                             "consoleMigrationStatus": "Migrated"})
    run = _migrate(api, group="Servers")

    assert len(api.moves) == 1
    move = api.moves[0]
    assert move["token"] == "tok-servers"
    assert move["ids"] == ["a1", "a2"]          # a3 already moved
    assert move["filter"]["groupIds"] == ["G1"]
    assert move["filter"]["consoleMigrationStatusesNin"] == ["Migrated"]
    assert [a["Computer"] for a in run["agents"]] == ["WIN-SRV-01",
                                                      "WIN-SRV-02"]


def test_a_console_that_rejects_the_nin_filter_still_skips_migrated():
    """Some consoles 400 on consoleMigrationStatusesNin as a GET param —
    the group must still be enumerated, minus the agents already moved."""
    api = _source_console()
    api.agents["G1"] = [{"id": "a1"},
                        {"id": "a2", "consoleMigrationStatus": "Migrated"}]
    plain = api.get_agents

    def picky(params=None, **kw):
        if "consoleMigrationStatusesNin" in (params or {}):
            raise S1APIError("GET /agents → 400", 400, "Unknown field")
        return plain(params=params, **kw)

    api.get_agents = picky
    assert am.agent_ids_for_group(api, "G1") == ["a1"]


def test_a_real_api_error_is_not_swallowed_by_the_fallback():
    api = _source_console()

    def dead(params=None, **kw):
        raise S1APIError("GET /agents → 401", 401, "bad token")

    api.get_agents = dead
    try:
        am.agent_ids_for_group(api, "G1")
    except S1APIError as e:
        assert e.status_code == 401
    else:
        raise AssertionError("a 401 must propagate")


def test_large_groups_are_sent_in_batches():
    api = _source_console()
    api.agents["G1"] = [{"id": f"a{i}", "computerName": f"PC-{i}"}
                        for i in range(2500)]
    api.sites[0]["groups"][0]["totalAgents"] = 2500
    run = _migrate(api, group="Servers")
    assert [len(m["ids"]) for m in api.moves] == [1000, 1000, 500]
    assert run["sent"] == 2500 and run["affected"] == 2500


def test_each_group_is_moved_with_its_own_destination_token():
    """The whole reason this page exists: structure is preserved."""
    api = _source_console()
    plan = _plan_for(api)
    run = am.run_live_migration(api, plan["rows"], verify=False)

    by_group = {m["filter"]["groupIds"][0]: m["token"] for m in api.moves}
    assert by_group == {
        "G1": "tok-servers",    # group's own token
        "G2": "tok-hq",         # no group token → its site's
        "G3": "tok-default",
    }
    assert run["sent"] == 4 and run["affected"] == 4
    assert plan["unmatched"] == [] and run["errors"] == []
    assert plan["empty_groups"] == 1            # "Empty" was skipped
    assert run["groups"] == 3


def test_a_renamed_group_is_skipped_and_named_not_mis_migrated():
    api = _source_console()
    data = _map()
    data[0]["sites"][0]["groups"][0]["name"] = "Server Group"   # was Servers
    plan = _plan_for(api, data)
    am.run_live_migration(api, plan["rows"], verify=False)

    assert [m["filter"]["groupIds"][0] for m in api.moves] == ["G2", "G3"]
    assert len(plan["unmatched"]) == 1
    miss = plan["unmatched"][0]
    assert miss["kind"] == "group" and miss["name"] == "Servers"
    assert miss["path"] == "Acme / HQ"
    assert "Server Group" in miss["candidates"]
    # …and the resolver turns that into a matching run
    assert am.rename_in_map(data, "group", "Server Group", "Servers") is True
    again = _plan_for(_source_console(), data)
    assert again["unmatched"] == [] and again["agents"] == 4


def test_a_renamed_site_skips_only_that_site():
    api = _source_console()
    data = _map()
    data[0]["sites"][1]["name"] = "Branch Office"
    plan = _plan_for(api, data)
    am.run_live_migration(api, plan["rows"], verify=False)
    assert [m["filter"]["groupIds"][0] for m in api.moves] == ["G1", "G2"]
    assert [u["kind"] for u in plan["unmatched"]] == ["site"]


def test_an_unmatched_account_stops_before_touching_anything():
    api = _source_console()
    data = _map()
    data[0]["name"] = "Acme Holdings"
    plan = _plan_for(api, data)
    am.run_live_migration(api, plan["rows"], verify=False)
    assert api.moves == []
    assert plan["unmatched"][0]["kind"] == "account"
    assert plan["ready"] == 0


def test_a_destination_scope_with_no_token_is_an_error_not_a_crash():
    api = _source_console()
    data = _map()
    data[0]["sites"][0]["token"] = ""
    data[0]["sites"][0]["groups"][1]["token"] = ""   # Laptops had none either
    plan = _plan_for(api, data)
    am.run_live_migration(api, plan["rows"], verify=False)
    assert any(r["Status"] == am.NO_TOKEN for r in plan["rows"])
    # the other groups still migrated
    assert [m["filter"]["groupIds"][0] for m in api.moves] == ["G1", "G3"]


def test_stopping_ends_the_walk_and_says_so():
    api = _source_console()
    plan = am.build_match_plan(api, _map(), "100",
                               should_stop=lambda: True)
    assert plan["stopped"] is True
    assert plan["rows"] == [] and api.moves == []


def test_a_single_site_can_be_migrated_on_its_own():
    api = _source_console()
    plan = am.build_match_plan(api, _map(), "100", site_id="S2")
    am.run_live_migration(api, plan["rows"], verify=False)
    assert [m["filter"]["groupIds"][0] for m in api.moves] == ["G3"]
    assert plan["agents"] == 1


# ── many accounts (a 60+ account console in one run) ────────────────────

class MultiConsole:
    """A console with many accounts, each with its own sites and groups."""

    def __init__(self, n_accounts=64, sites_per_account=2, groups_per_site=3):
        self.accounts, self.sites, self.groups = [], {}, {}
        self.agents = {}
        self.moves = []
        for a in range(1, n_accounts + 1):
            aid = f"A{a}"
            self.accounts.append({"id": aid, "name": f"Customer {a}"})
            self.sites[aid] = []
            for s in range(1, sites_per_account + 1):
                sid = f"{aid}-S{s}"
                self.sites[aid].append(
                    {"id": sid, "name": f"Site {s}",
                     "registrationToken": f"tok-{sid}"})
                self.groups[sid] = []
                for g in range(1, groups_per_site + 1):
                    gid = f"{sid}-G{g}"
                    self.groups[sid].append(
                        {"id": gid, "name": f"Group {g}", "totalAgents": 1,
                         "registrationToken": f"tok-{gid}"})
                    self.agents[gid] = [{"id": f"{gid}-a1"}]

    def get_accounts(self, **kw):
        return [dict(a) for a in self.accounts]

    def get_account_by_id(self, account_id):
        return next((dict(a) for a in self.accounts
                     if a["id"] == str(account_id)), None)

    def get_sites(self, params=None, **kw):
        return [dict(s) for s in self.sites.get(
            str((params or {}).get("accountId", "")), [])]

    def get_groups(self, params=None, **kw):
        return [dict(g) for g in self.groups.get(
            str((params or {}).get("siteIds", "")), [])]

    def get_agents(self, params=None, **kw):
        return list(self.agents.get(str((params or {}).get("groupIds", "")),
                                    []))

    def move_agents_to_console(self, agent_ids, token, extra_filter=None):
        self.moves.append({"ids": list(agent_ids), "token": token,
                           "filter": dict(extra_filter or {})})
        return {"data": {"affected": len(agent_ids)}}


def test_a_blank_account_field_maps_the_whole_console():
    api = MultiConsole(n_accounts=64)
    data = am.build_scope_map(api, "")
    assert am.map_counts(data) == (64, 128, 384)
    # order is preserved even though groups are fetched in parallel
    assert [a["name"] for a in data[:3]] == ["Customer 1", "Customer 2",
                                             "Customer 3"]
    assert [s["name"] for s in data[0]["sites"]] == ["Site 1", "Site 2"]
    assert [g["name"] for g in data[0]["sites"][0]["groups"]] == \
        ["Group 1", "Group 2", "Group 3"]


def test_a_few_account_ids_map_only_those():
    api = MultiConsole(n_accounts=64)
    data = am.build_scope_map(api, "A3, A7 A11")
    assert [a["id"] for a in data] == ["A3", "A7", "A11"]
    assert am.map_counts(data) == (3, 6, 18)


def test_one_unreachable_id_in_a_list_is_named_not_skipped():
    api = MultiConsole(n_accounts=4)
    try:
        am.build_scope_map(api, "A1, A99, A2")
    except ValueError as e:
        assert "A99" in str(e) and "A1" not in str(e).replace("A99", "")
    else:
        raise AssertionError("expected a ValueError naming A99")


def test_stopping_a_long_map_keeps_what_it_already_walked():
    api = MultiConsole(n_accounts=64)
    seen = {"n": 0}

    def stop():
        seen["n"] += 1
        return seen["n"] > 3        # let a few accounts through

    data = am.build_scope_map(api, "", should_stop=stop)
    assert 0 < len(data) < 64


def test_the_whole_console_migrates_in_one_run():
    api = MultiConsole(n_accounts=64)
    map_data = am.build_scope_map(MultiConsole(n_accounts=64), "")

    plan = am.build_match_plan(api, map_data, "")
    run = am.run_live_migration(api, plan["rows"], verify=False)

    assert plan["accounts"] == 64
    assert plan["ready"] == 384 and plan["blocked"] == 0
    assert plan["agents"] == 384
    assert run["sent"] == 384 and run["affected"] == 384
    assert plan["unmatched"] == [] and run["errors"] == []
    # every group still went to its OWN token
    assert all(m["token"] == f"tok-{m['filter']['groupIds'][0]}"
               for m in api.moves)
    # and every account is named in the plan the operator reviewed
    assert {r["Account"] for r in plan["rows"]} == \
        {f"Customer {i}" for i in range(1, 65)}


def test_one_renamed_account_does_not_stop_the_other_63():
    api = MultiConsole(n_accounts=64)
    map_data = am.build_scope_map(MultiConsole(n_accounts=64), "")
    map_data[5]["name"] = "Customer Six (renamed)"

    plan = am.build_match_plan(api, map_data, "")

    assert plan["accounts"] == 64
    assert plan["ready"] == 384 - 6
    assert [u["kind"] for u in plan["unmatched"]] == ["account"]
    assert plan["unmatched"][0]["name"] == "Customer 6"
    # the operator sees one row explaining the whole missing account
    blocked = [r for r in plan["rows"] if r["state"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["Account"] == "Customer 6"
    assert blocked[0]["Status"] == am.NO_MATCH_ACCOUNT


def test_a_subset_of_accounts_can_be_migrated_from_a_full_map():
    api = MultiConsole(n_accounts=64)
    map_data = am.build_scope_map(MultiConsole(n_accounts=64), "")

    plan = am.build_match_plan(api, map_data, "A2 A5")

    assert plan["accounts"] == 2
    assert {r["Account"] for r in plan["rows"]} == {"Customer 2",
                                                    "Customer 5"}


# ── status report ───────────────────────────────────────────────────────

class StatusAPI:
    def __init__(self, by_status, decommissioned=None, decom_error=False):
        self.by_status = by_status
        self.decommissioned = decommissioned or []
        self.decom_error = decom_error
        self.seen = []
        self.passphrase_calls = 0

    def get_agents(self, params=None, **kw):
        params = dict(params or {})
        self.seen.append(params)
        if params.get("isDecommissioned"):
            if self.decom_error:
                raise RuntimeError("no permission")
            return list(self.decommissioned)
        return list(self.by_status.get(params.get("consoleMigrationStatuses"),
                                       []))

    def get_agent_passphrase(self, agent_id):
        self.passphrase_calls += 1
        return [{"passphrase": f"pp-{agent_id}"}]


def test_status_counts_every_migration_state():
    api = StatusAPI({
        "Migrated": [{"id": "1", "computerName": "PC1"},
                     {"id": "2", "computerName": "PC2"}],
        "Pending": [{"id": "3", "computerName": "PC3"}],
        "N/A": [],
        "Failed": [{"id": "4", "computerName": "PC4"}],
    }, decommissioned=[{"id": "9", "computerName": "OLD",
                        "isDecommissioned": True}])

    result = am.count_agents_by_status(api, account_ids="100")
    assert result["counts"] == {"Migrated": 2, "Pending": 1, "N/A": 0,
                                "Failed": 1}
    assert len(result["agents"]) == 4
    assert len(result["decommissioned"]) == 1
    assert result["decommissioned"][0]["Decommissioned"] == "Yes"
    # the literal "N/A" is sent as-is; requests encodes it
    assert any(p.get("consoleMigrationStatuses") == "N/A" for p in api.seen)
    # account scope unless a site is given
    assert all(p.get("accountIds") == "100" for p in api.seen)


def test_a_site_id_overrides_the_account_scope():
    api = StatusAPI({s: [] for s in am.MIGRATION_STATUSES})
    am.count_agents_by_status(api, account_ids="100", site_id="S2")
    assert all(p.get("siteIds") == "S2" for p in api.seen)
    assert not any("accountIds" in p for p in api.seen)


def test_the_status_report_can_span_several_accounts_or_the_whole_console():
    api = StatusAPI({s: [] for s in am.MIGRATION_STATUSES})
    am.count_agents_by_status(api, account_ids="100, 200 300")
    assert all(p.get("accountIds") == "100,200,300" for p in api.seen)

    api = StatusAPI({s: [] for s in am.MIGRATION_STATUSES})
    am.count_agents_by_status(api)          # blank = everything visible
    assert not any("accountIds" in p or "siteIds" in p for p in api.seen)


def test_passphrases_are_only_fetched_when_asked_for():
    rows = {"Migrated": [{"id": "1", "computerName": "PC1"}],
            "Pending": [], "N/A": [], "Failed": []}
    api = StatusAPI(rows)
    result = am.count_agents_by_status(api, account_ids="100")
    assert api.passphrase_calls == 0
    assert result["agents"][0]["Passphrase"] == "not fetched"

    api = StatusAPI(rows)
    result = am.count_agents_by_status(api, account_ids="100",
                                       fetch_passphrases=True)
    assert api.passphrase_calls == 1
    assert result["agents"][0]["Passphrase"] == "pp-1"
    assert "sensitive" in am.status_summary_text(result)


def test_a_decommissioned_listing_failure_does_not_lose_the_report():
    api = StatusAPI({s: [] for s in am.MIGRATION_STATUSES}, decom_error=True)
    said = []
    result = am.count_agents_by_status(api, account_ids="100",
                                       log=said.append)
    assert result["decommissioned"] == []
    assert any("decommissioned" in m for m in said)


# ── scheduling ──────────────────────────────────────────────────────────

def test_a_schedule_must_be_a_future_moment():
    now = datetime(2026, 9, 17, 12, 0)
    assert am.parse_schedule("2026-09-17", "18:30", now=now) == \
        datetime(2026, 9, 17, 18, 30)
    for date, time in (("17/09/2026", "18:30"), ("2026-09-17", "6pm")):
        try:
            am.parse_schedule(date, time, now=now)
        except ValueError as e:
            assert "YYYY-MM-DD" in str(e)
        else:
            raise AssertionError(f"expected {date} {time} to be rejected")
    try:
        am.parse_schedule("2026-09-17", "11:00", now=now)
    except ValueError as e:
        assert "passed" in str(e)
    else:
        raise AssertionError("a past time must be rejected")


# ── API envelope ────────────────────────────────────────────────────────

def test_move_to_console_sends_ids_inside_the_filter():
    api = S1API("https://x.sentinelone.net", "t")
    sent = {}
    api._post = lambda endpoint, body=None: sent.update(
        endpoint=endpoint, body=body) or {"data": {"affected": 2}}

    api.move_agents_to_console(
        ["a1", "a2"], "tok",
        {"groupIds": ["G1"], "consoleMigrationStatusesNin": ["Migrated"]})

    assert sent["endpoint"] == "/agents/actions/move-to-console"
    assert sent["body"] == {
        "filter": {"groupIds": ["G1"],
                   "consoleMigrationStatusesNin": ["Migrated"],
                   "ids": ["a1", "a2"]},
        "data": {"token": "tok"}}


# ── step 2: the match plan ──────────────────────────────────────────────

def test_the_plan_names_every_source_scope_and_where_it_lands():
    """The operator's actual question: did it find MY accounts, sites and
    groups, and what is each one paired with?"""
    plan = am.build_match_plan(_source_console(), _map(), "100")

    assert plan["accounts"] == 1
    assert plan["ready"] == 3 and plan["blocked"] == 0
    assert plan["agents"] == 4
    assert plan["empty_groups"] == 1          # "Empty" never appears

    servers = plan["rows"][0]
    assert (servers["Account"], servers["Site"], servers["Group"]) == \
        ("Acme", "HQ", "Servers")
    assert servers["Destination"] == "Acme / HQ / Servers"
    assert servers["Agents"] == 2
    assert servers["token"] == "tok-servers"
    assert servers["token_from"] == "group"
    # Laptops has no token of its own, so it inherits HQ's
    laptops = plan["rows"][1]
    assert laptops["token"] == "tok-hq" and laptops["token_from"] == "site"


def test_the_plan_streams_each_row_as_it_resolves():
    """A 64-account walk takes minutes; the list fills as it goes."""
    seen = []
    plan = am.build_match_plan(_source_console(), _map(), "100",
                               on_row=lambda r: seen.append(
                                   (r["Group"], r["Agents"], r["counted"])))
    # pass 1 pairs every scope, pass 2 corrects the counts
    assert seen[:3] == [("Servers", 2, False), ("Laptops", 1, False),
                        ("Default Group", 1, False)]
    assert sorted(seen[3:]) == [("Default Group", 1, True),
                                ("Laptops", 1, True), ("Servers", 2, True)]
    assert [r["Group"] for r in plan["rows"]] == ["Servers", "Laptops",
                                                  "Default Group"]


def test_the_pairing_pass_alone_never_reads_a_group():
    """Pass 1 must cost nothing per group — that was the whole delay."""
    api = _source_console()
    reads = []
    plain = api.get_agents
    api.get_agents = lambda params=None, **kw: (reads.append(params),
                                                plain(params=params, **kw))[1]
    plan = am.build_match_plan(api, _map(), "100", count_agents=False)

    assert reads == []
    assert plan["counted"] is False
    assert plan["ready"] == 3
    # the group listing's own total stands in until the count runs
    assert [r["Agents"] for r in plan["rows"]] == [2, 1, 1]
    assert all(r["counted"] is False for r in plan["rows"])


def test_counting_runs_in_parallel_and_corrects_the_totals():
    api = _source_console()
    # G1 says 2 agents, but one of them already migrated
    api.agents["G1"][1]["consoleMigrationStatus"] = "Migrated"
    plan = am.build_match_plan(api, _map(), "100", count_agents=False)
    assert plan["agents"] == 4                  # the optimistic total

    # All three counts must be in flight together — if they ran one after
    # another this barrier never fills and the reads fail.
    barrier = threading.Barrier(3, timeout=5)
    plain = api.get_agents

    def watched(params=None, **kw):
        barrier.wait()
        return plain(params=params, **kw)

    api.get_agents = watched
    am.refine_plan_counts(api, plan)

    assert plan["ready"] == 3, "the counts did not run concurrently"
    assert plan["counted"] is True
    assert plan["agents"] == 3                  # the real one
    assert [r["Agents"] for r in plan["rows"]] == [1, 1, 1]
    assert all(r["counted"] is True for r in plan["rows"])


def test_counting_a_huge_console_does_not_open_a_thread_per_group():
    api = MultiConsole(n_accounts=64)
    plan = am.build_match_plan(api, am.build_scope_map(
        MultiConsole(n_accounts=64), ""), "", count_agents=False)
    assert plan["ready"] == 384

    live = set()
    peak = {"n": 0}
    lock = threading.Lock()
    plain = api.get_agents

    def watched(params=None, **kw):
        with lock:
            live.add(threading.current_thread())
            peak["n"] = max(peak["n"], len(live))
        try:
            return plain(params=params, **kw)
        finally:
            with lock:
                live.discard(threading.current_thread())

    api.get_agents = watched
    am.refine_plan_counts(api, plan)

    assert plan["agents"] == 384
    assert peak["n"] <= am.COUNT_WORKERS


def test_a_group_that_cannot_be_read_is_blocked_by_the_count():
    api = _source_console()
    plan = am.build_match_plan(api, _map(), "100", count_agents=False)

    def dead(params=None, **kw):
        raise S1APIError("GET /agents → 403", 403, "no permission")

    api.get_agents = dead
    am.refine_plan_counts(api, plan)

    assert plan["ready"] == 0 and plan["blocked"] == 3
    assert all(r["Status"] == am.UNREADABLE for r in plan["rows"])
    assert "403" in plan["rows"][0]["reason"]


def test_a_group_with_no_twin_is_blocked_with_a_reason_a_human_can_act_on():
    data = _map()
    data[0]["sites"][0]["groups"][0]["name"] = "Server Group"
    plan = am.build_match_plan(_source_console(), data, "100")

    blocked = [r for r in plan["rows"] if r["state"] == "blocked"]
    assert len(blocked) == 1
    row = blocked[0]
    assert row["Group"] == "Servers"
    assert row["Status"] == am.NO_MATCH_GROUP
    assert row["kind"] == "group"                  # the fixer can act on it
    assert "no group named 'Servers'" in row["reason"]
    assert "2 agent(s) stay put" in row["reason"]
    # and it is not counted as migratable
    assert plan["ready"] == 2 and plan["agents"] == 2


def test_a_scope_with_nowhere_to_land_says_to_make_a_token():
    data = _map()
    data[0]["sites"][0]["token"] = ""
    data[0]["sites"][0]["groups"][1]["token"] = ""
    plan = am.build_match_plan(_source_console(), data, "100")

    row = [r for r in plan["rows"] if r["Group"] == "Laptops"][0]
    assert row["Status"] == am.NO_TOKEN
    assert "registration token" in row["reason"]
    assert row["Destination"] == "Acme / HQ / Laptops"   # it DID match


def test_a_group_whose_agents_already_moved_is_done_not_blocked():
    api = _source_console()
    for agent in api.agents["G1"]:
        agent["consoleMigrationStatus"] = "Migrated"
    plan = am.build_match_plan(api, _map(), "100")

    row = [r for r in plan["rows"] if r["Group"] == "Servers"][0]
    assert row["state"] == "done" and row["Status"] == am.ALL_DONE
    assert plan["blocked"] == 0
    assert plan["agents"] == 2          # only Laptops + Default Group


def test_the_plan_summary_names_every_scope_that_will_not_move():
    data = _map()
    data[0]["sites"][0]["groups"][0]["name"] = "Server Group"
    plan = am.build_match_plan(_source_console(), data, "100")
    text = am.plan_summary_text(plan)

    assert "nothing has moved" in text
    assert "Agents to migrate:  2" in text
    assert "Acme / HQ / Servers" in text
    assert am.NO_MATCH_GROUP in text


def test_an_unmatched_account_blocks_everything_under_it():
    data = _map()
    data[0]["name"] = "Acme Holdings"
    plan = am.build_match_plan(_source_console(), data, "100")
    assert [r["Status"] for r in plan["rows"]] == [am.NO_MATCH_ACCOUNT]
    assert plan["agents"] == 0


# ── remembering the plan ───────────────────────────────────────────────

def _fp(map_data, **kw):
    args = {"source_url": "https://src.sentinelone.net", "account_ids": "100",
            "site_id": "", "map_path": "/tmp/map.json"}
    args.update(kw)
    return am.plan_fingerprint(map_data=map_data, **args)


def test_a_saved_plan_comes_back_without_touching_the_console(tmp_path):
    """The whole point: reopening the app must not re-walk the console."""
    api = _source_console()
    data = _map()
    plan = am.build_match_plan(api, data, "100")
    path = str(tmp_path / "plan.json")
    am.save_plan(plan, _fp(data), path)

    api.moves = []
    restored, saved_at = am.load_plan(_fp(data), data, path)

    assert restored is not None
    assert saved_at
    assert restored["ready"] == 3 and restored["agents"] == 4
    assert [r["Group"] for r in restored["rows"]] == ["Servers", "Laptops",
                                                      "Default Group"]
    # and it is good enough to migrate from, untouched
    am.run_live_migration(api, restored["rows"], verify=False)
    assert {m["filter"]["groupIds"][0]: m["token"] for m in api.moves} == {
        "G1": "tok-servers", "G2": "tok-hq", "G3": "tok-default"}


def test_tokens_are_never_written_to_the_cache(tmp_path):
    data = _map()
    plan = am.build_match_plan(_source_console(), data, "100")
    path = str(tmp_path / "plan.json")
    am.save_plan(plan, _fp(data), path)

    raw = (tmp_path / "plan.json").read_text(encoding="utf-8")
    assert "tok-servers" not in raw and "tok-hq" not in raw
    # they come back from the map instead
    restored, _ = am.load_plan(_fp(data), data, path)
    assert restored["rows"][0]["token"] == "tok-servers"


def test_a_plan_built_for_other_inputs_is_not_reused(tmp_path):
    data = _map()
    plan = am.build_match_plan(_source_console(), data, "100")
    path = str(tmp_path / "plan.json")
    am.save_plan(plan, _fp(data), path)

    # a different source console
    assert am.load_plan(_fp(data, source_url="https://other.sentinelone.net"),
                        data, path) == (None, "")
    # a different account scope
    assert am.load_plan(_fp(data, account_ids="200"), data, path) == (None, "")
    # a different site scope
    assert am.load_plan(_fp(data, site_id="S2"), data, path) == (None, "")
    # the map file itself changed
    changed = _map()
    changed[0]["sites"][0]["groups"][0]["name"] = "Renamed"
    assert am.load_plan(_fp(changed), changed, path) == (None, "")


def test_a_rotated_token_is_picked_up_on_restore(tmp_path):
    data = _map()
    plan = am.build_match_plan(_source_console(), data, "100")
    path = str(tmp_path / "plan.json")
    fingerprint = _fp(data)
    am.save_plan(plan, fingerprint, path)

    data[0]["sites"][0]["groups"][0]["token"] = "tok-rotated"
    restored, _ = am.load_plan(fingerprint, data, path)
    assert restored["rows"][0]["token"] == "tok-rotated"


def test_a_scope_dropped_from_the_map_blocks_instead_of_migrating(tmp_path):
    data = _map()
    plan = am.build_match_plan(_source_console(), data, "100")
    path = str(tmp_path / "plan.json")
    fingerprint = _fp(data)
    am.save_plan(plan, fingerprint, path)

    del data[0]["sites"][0]["groups"][0]          # Servers is gone
    restored, _ = am.load_plan(fingerprint, data, path)

    row = [r for r in restored["rows"] if r["Group"] == "Servers"][0]
    assert row["state"] == "blocked" and row["token"] == ""
    assert "no longer in the map file" in row["reason"]
    assert restored["ready"] == 2


def test_a_scope_whose_token_was_revoked_blocks_on_restore(tmp_path):
    data = _map()
    plan = am.build_match_plan(_source_console(), data, "100")
    path = str(tmp_path / "plan.json")
    fingerprint = _fp(data)
    am.save_plan(plan, fingerprint, path)

    data[0]["sites"][0]["token"] = ""
    data[0]["sites"][0]["groups"][1]["token"] = ""   # Laptops relied on HQ's
    restored, _ = am.load_plan(fingerprint, data, path)

    row = [r for r in restored["rows"] if r["Group"] == "Laptops"][0]
    assert row["state"] == "blocked" and row["Status"] == am.NO_TOKEN


def test_a_missing_or_corrupt_cache_is_simply_no_cache(tmp_path):
    data = _map()
    missing = str(tmp_path / "nope.json")
    assert am.load_plan(_fp(data), data, missing) == (None, "")

    junk = tmp_path / "junk.json"
    junk.write_text("{not json", encoding="utf-8")
    assert am.load_plan(_fp(data), data, str(junk)) == (None, "")

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert am.load_plan(_fp(data), data, str(empty)) == (None, "")


def test_forgetting_a_plan_is_safe_when_there_is_none(tmp_path):
    am.forget_plan(str(tmp_path / "nothing.json"))       # must not raise
    data = _map()
    path = str(tmp_path / "plan.json")
    am.save_plan(am.build_match_plan(_source_console(), data, "100"),
                 _fp(data), path)
    am.forget_plan(path)
    assert am.load_plan(_fp(data), data, path) == (None, "")


def test_the_cache_lives_beside_the_app_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(am.config, "CONFIG_DIR", str(tmp_path))
    assert am.plan_cache_path() == str(tmp_path / am.PLAN_CACHE_NAME)


def test_a_plans_age_is_stated_in_words():
    now = datetime.now()
    assert am.plan_age(now.isoformat()) == "just now"
    assert am.plan_age((now - timedelta(minutes=5)).isoformat()) == \
        "5 minutes ago"
    assert am.plan_age((now - timedelta(hours=3)).isoformat()) == "3 hours ago"
    assert am.plan_age((now - timedelta(days=2)).isoformat()) == "2 days ago"
    assert am.plan_age("") == "earlier"


# ── step 3: the live run ────────────────────────────────────────────────

def test_the_live_run_reports_every_agent_by_name():
    api = _source_console()
    events = []
    run = am.run_live_migration(api, _plan_for(api)["rows"],
                                on_event=events.append)

    assert run["moved"] == 4 and run["failed"] == 0
    by_name = {a["Computer"]: a for a in run["agents"]}
    assert set(by_name) == {"WIN-SRV-01", "WIN-SRV-02", "MAC-DEV-07",
                            "LNX-BUILD-3"}
    assert by_name["WIN-SRV-01"]["Result"] == "moved"
    assert by_name["WIN-SRV-01"]["OS"] == "Windows Server 2019"
    assert by_name["WIN-SRV-01"]["Destination"] == "Acme / HQ / Servers"
    # each group still went with its own token
    assert {m["filter"]["groupIds"][0]: m["token"] for m in api.moves} == {
        "G1": "tok-servers", "G2": "tok-hq", "G3": "tok-default"}


def test_the_live_run_announces_the_request_before_it_sends_it():
    api = _source_console()
    events = []
    am.run_live_migration(api, _plan_for(api)["rows"], on_event=events.append)

    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    request = next(e for e in events if e["type"] == "request")
    assert request["endpoint"] == "/agents/actions/move-to-console"
    assert request["count"] == 2
    assert request["filter"]["groupIds"] == ["G1"]
    # the token is never printed in full
    assert request["token"] == "…servers" or request["token"].startswith("…")
    assert "tok-servers" != request["token"]
    # every agent is shown as sending before its result arrives
    states = [e["rec"]["Result"] for e in events
              if e["type"] == "agent" and e["rec"]["id"] == "a1"]
    assert states[0] == "sending" and states[-1] == "moved"


def test_a_rejected_batch_marks_each_of_its_agents_failed_with_the_reason():
    """The console answers a batch, not an agent — so when it refuses, the
    operator must still see which machines were in that batch and why."""
    api = _source_console(fail_moves=True)
    run = am.run_live_migration(api, _plan_for(api)["rows"])

    assert run["moved"] == 0 and run["failed"] == 4
    assert all(a["Result"] == "failed" for a in run["agents"])
    assert all("console refused the move" in a["Detail"]
               for a in run["agents"])
    assert any("Acme / HQ / Servers" in e for e in run["errors"])


def test_an_accepted_agent_is_read_back_before_it_counts_as_moved():
    """`affected` only means the console took the request."""
    api = _source_console(verify_as="Pending")
    run = am.run_live_migration(api, _plan_for(api)["rows"])

    assert run["affected"] == 4          # the console accepted all four
    assert run["moved"] == 0             # but none has actually moved yet
    assert run["pending"] == 4
    assert api.id_lookups                # it really did read them back
    offline = [a for a in run["agents"] if a["Computer"] == "WIN-SRV-02"][0]
    assert "offline" in offline["Detail"]
    online = [a for a in run["agents"] if a["Computer"] == "WIN-SRV-01"][0]
    assert "checks in" in online["Detail"]


def test_an_agent_the_console_reports_as_failed_says_so():
    api = _source_console(verify_as="Failed")
    run = am.run_live_migration(api, _plan_for(api)["rows"])
    assert run["failed"] == 4 and run["moved"] == 0
    assert all("reports the migration as failed" in a["Detail"]
               for a in run["agents"])


def test_skipping_the_read_back_is_honest_about_what_it_knows():
    api = _source_console()
    run = am.run_live_migration(api, _plan_for(api)["rows"], verify=False)
    assert api.id_lookups == []
    assert run["verified"] is False
    assert run["pending"] == 4 and run["moved"] == 0
    by_name = {a["Computer"]: a for a in run["agents"]}
    assert "not confirmed" in by_name["WIN-SRV-01"]["Detail"]
    assert "offline" in by_name["WIN-SRV-02"]["Detail"]
    assert "confirmation was off" in am.live_summary_text(run)


def test_blocked_rows_are_never_sent():
    data = _map()
    data[0]["sites"][0]["groups"][0]["name"] = "Server Group"
    api = _source_console()
    plan = am.build_match_plan(api, data, "100")
    am.run_live_migration(api, plan["rows"])
    assert [m["filter"]["groupIds"][0] for m in api.moves] == ["G2", "G3"]


def test_stopping_the_live_run_leaves_the_rest_untouched():
    api = _source_console()
    run = am.run_live_migration(api, _plan_for(api)["rows"],
                                should_stop=lambda: True)
    assert run["stopped"] is True and api.moves == []


def test_a_token_is_never_shown_in_full():
    assert am.mask_token("abcdefghijklmnop") == "…klmnop"
    assert "abcdefghij" not in am.mask_token("abcdefghijklmnop")
    assert am.mask_token("") == "(none)"
    assert am.mask_token("short") == "…"


def test_the_live_summary_names_the_machines_that_failed():
    api = _source_console(fail_moves=True)
    run = am.run_live_migration(api, _plan_for(api)["rows"])
    text = am.live_summary_text(run)
    assert "LIVE MIGRATION" in text
    assert "WIN-SRV-01" in text and "console refused the move" in text


# ── picking scopes from a list ──────────────────────────────────────────

def test_several_sites_reach_the_api_as_one_comma_list():
    """The chooser can return more than one site; `siteIds` takes them
    comma-separated, and typing them with spaces must work too."""
    api = _source_console()
    seen = []
    real = api.get_sites
    api.get_sites = lambda params=None, **kw: (
        seen.append(dict(params or {})), real(params=params, **kw))[1]
    am.build_scope_map(api, "", "S1, S2")
    assert seen[-1]["siteIds"] == "S1,S2"
    seen.clear()
    am.build_scope_map(api, "", "  ")
    assert "siteIds" not in seen[-1]        # blank is not a filter


def test_several_sites_scope_the_status_report_too():
    api = _source_console()
    seen = []
    real = api.get_agents
    api.get_agents = lambda params=None, **kw: (
        seen.append(dict(params or {})), real(params=params, **kw))[1]
    am.count_agents_by_status(api, "", "S1 S2")
    assert seen[0]["siteIds"] == "S1,S2"


def test_the_cached_plan_ignores_how_the_ids_were_typed():
    """'S1, S2' and 'S1 S2' are the same scope and must not invalidate."""
    a = am.plan_fingerprint("u", "", "S1, S2", "m.json", [])
    b = am.plan_fingerprint("u", "", "S1  S2", "m.json", [])
    assert a == b


def test_the_chooser_returns_what_was_ticked():
    src = inspect.getsource(am._ChoiceDialog)
    # ticking nothing means "everything", which is what blank already means
    assert "Nothing ticked — that means everything" in src
    assert "self._result = None" in src          # cancel changes nothing
    assert "list(self._chosen)" in inspect.getsource(am._ChoiceDialog._accept)


def test_every_scope_field_can_be_chosen_from_a_list():
    src = inspect.getsource(am.AgentMigratorPage)
    for entry in ("map_account", "map_site", "match_account", "match_site",
                  "status_account", "status_site"):
        assert f"self.{entry} = form.field(" in src
    # three panels × two fields, each wired to a chooser
    assert src.count("self._choose_accounts(") == 3
    assert src.count("self._choose_sites(") == 3


# ── the chooser on a console with thousands of scopes ───────────────────
#
# Two habits make a picker unusable at that size, and both were present:
# fetching every page before showing anything, and building a widget per
# result. The second was brutal — growing a CTkScrollableFrame measured
# 2.3s for 50 rows, 112s for 200 and ~14 minutes for 400, because each
# insert relayouts the whole tree. These pin down both fixes.

def _dialog(monkeypatch, fetch, **kw):
    """A chooser with its worker thread run inline, or a skip if there
    is no display to build one on."""
    try:
        root = am.ctk.CTk()
    except Exception as exc:                      # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    monkeypatch.setattr(am._ChoiceDialog, "_spawn",
                        lambda self, work, done, failed: done(work()))
    dlg = am._ChoiceDialog(root, "Pick", fetch, **kw)
    dlg.withdraw()
    dlg._search_now()                             # the initial page
    return root, dlg


def test_the_chooser_never_asks_the_console_for_everything(monkeypatch):
    """A console with 20,000 sites must cost one bounded page."""
    asked = []

    def fetch(query, limit):
        asked.append((query, limit))
        return [(str(i), f"Site {i}", f"id {i}") for i in range(20_000)][:limit]

    root, dlg = _dialog(monkeypatch, fetch)
    try:
        assert asked, "the chooser never asked the console anything"
        assert all(limit <= am._ChoiceDialog.PAGE + 1 for _q, limit in asked), (
            f"asked for {asked} — a picker must bound its page")
        assert len(dlg._shown) == am._ChoiceDialog.PAGE
        assert dlg._more is True                  # and says so
    finally:
        root.destroy()


def test_the_chooser_never_grows_a_widget_per_result(monkeypatch):
    """The pool is built once; searching rebinds it and creates nothing."""
    def fetch(query, limit):
        rows = [(str(i), f"Account {i}", f"id {i}") for i in range(500)]
        if query:
            rows = [r for r in rows if query in r[1]]
        return rows[:limit]

    root, dlg = _dialog(monkeypatch, fetch)
    try:
        before = len(dlg._inner.winfo_children())
        for term in ("1", "12", "123", "", "9"):
            dlg._search.delete(0, "end")
            dlg._search.insert(0, term)
            dlg._search_now()
        assert len(dlg._inner.winfo_children()) == before, (
            "searching created widgets; the row pool must be reused")
        assert before <= am._ChoiceDialog.PAGE + 1
    finally:
        root.destroy()


def test_a_tick_survives_being_searched_away(monkeypatch):
    """Tick a site, search for something else, and it must stay ticked —
    the selection outlives the rows showing it."""
    def fetch(query, limit):
        rows = [("s1", "Alpha", "id s1"), ("s2", "Beta", "id s2")]
        if query:
            rows = [r for r in rows if query.lower() in r[1].lower()]
        return rows[:limit]

    root, dlg = _dialog(monkeypatch, fetch)
    try:
        dlg._rows[0]["var"].set(True)
        dlg._toggle(0)                            # tick Alpha
        assert "s1" in dlg._chosen
        dlg._search.insert(0, "Beta")             # Alpha is now off screen
        dlg._search_now()
        assert [r[0] for r in dlg._shown] == ["s2"]
        assert "s1" in dlg._chosen, "a tick was lost by searching"
        assert "not shown by this search" in dlg._count.cget("text")
        dlg._accept()
        assert dlg._result == ["s1"]
    finally:
        root.destroy()


def test_select_all_only_touches_what_is_on_screen(monkeypatch):
    """'All' after a search must not tick what the operator filtered out
    and cannot see — especially now the rest was never even fetched."""
    def fetch(query, limit):
        rows = [("a", "Alpha", ""), ("b", "Beta", ""), ("c", "Gamma", "")]
        if query:
            rows = [r for r in rows if query.lower() in r[1].lower()]
        return rows[:limit]

    root, dlg = _dialog(monkeypatch, fetch)
    try:
        dlg._search.insert(0, "a")                # Alpha, Beta, Gamma
        dlg._search_now()
        dlg._search.delete(0, "end")
        dlg._search.insert(0, "Alpha")
        dlg._search_now()
        dlg._set_all(True)
        assert list(dlg._chosen) == ["a"], (
            "'All' ticked rows that the search had hidden")
    finally:
        root.destroy()


def test_a_slow_search_cannot_overwrite_a_newer_one(monkeypatch):
    """Type fast and the first reply may land last; the newest search
    must win or the list contradicts the search box."""
    try:
        root = am.ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    held = []
    monkeypatch.setattr(am._ChoiceDialog, "_spawn",
                        lambda self, work, done, failed: held.append(
                            (work, done)))
    dlg = am._ChoiceDialog(root, "Pick",
                           lambda q, n: [(q or "none", f"for {q}", "")])
    dlg.withdraw()
    try:
        dlg._search.delete(0, "end")
        dlg._search.insert(0, "slow")
        dlg._search_now()
        dlg._search.delete(0, "end")
        dlg._search.insert(0, "fast")
        dlg._search_now()
        stale_work, stale_done = held[-2]
        fresh_work, fresh_done = held[-1]
        fresh_done(fresh_work())                  # newer answers first
        stale_done(stale_work())                  # older lands late
        assert [r[0] for r in dlg._shown] == ["fast"], (
            "a stale search result overwrote a newer one")
    finally:
        root.destroy()


def test_dismissing_the_chooser_mid_search_is_not_an_error(monkeypatch):
    """The window can be closed while a search is still in flight; the
    worker must not then schedule onto a destroyed widget."""
    try:
        root = am.ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    dlg = am._ChoiceDialog(root, "Pick", lambda q, n: [])
    dlg.withdraw()
    dlg._cancel()                                 # gone before work lands
    dlg._spawn(lambda: [("a", "A", "")], lambda _p: None, lambda _e: None)
    time.sleep(0.2)                               # let the thread finish
    root.destroy()


def test_labelling_a_site_costs_no_extra_account_walk():
    """The row subtitle used to be built by listing every account just to
    look up a name. The site payload already carries it."""
    src = inspect.getsource(am.AgentMigratorPage._choose_sites)
    assert "accountName" in src
    assert "get_accounts" not in src, (
        "the site chooser is walking every account again")
    assert "search_sites" in src                  # bounded, console-side


def test_bounded_lookups_ask_for_one_page_only():
    """`get_sites` walks every cursor page; the picker's variant must
    make exactly one request no matter how much is behind it."""
    calls = []

    class Api(S1API):
        def __init__(self):
            pass

        def _get(self, endpoint, params=None):
            calls.append((endpoint, dict(params or {})))
            return {"data": {"sites": [{"id": "s1", "name": "One"}]},
                    "pagination": {"nextCursor": "more-behind-this"}}

    api = Api()
    assert api.search_sites("prod", "A1,A2", limit=51) == [
        {"id": "s1", "name": "One"}]
    assert len(calls) == 1, "search_sites followed the cursor"
    _endpoint, params = calls[0]
    assert params["limit"] == 51
    assert params["query"] == "prod"              # console does the matching
    assert params["accountIds"] == "A1,A2"


# ── staying responsive on a big run ─────────────────────────────────────
#
# A row of widgets per agent, and a repaint per event, is what made the
# window stop responding mid-migration. These lock in the shape of the
# fix without needing a display.

def test_the_live_feed_never_grows_a_widget_per_agent():
    src = inspect.getsource(am._LiveFeed)
    assert "VISIBLE" in src
    # rows come from a fixed pool built once in __init__
    assert "self._pool = [self._make_row(i) for i in range(self.VISIBLE)]" \
        in src
    # …and _make_row is never called anywhere else
    assert src.count("_make_row(") == 2        # the definition and that line
    # put() records data; it must not build or configure widgets
    put = inspect.getsource(am._LiveFeed.put)
    assert "configure" not in put and "tk." not in put


def test_the_live_feed_rows_are_plain_tk_not_customtkinter():
    """A CTkLabel queues canvas redraw work on every configure; at a few
    hundred updates a run that is seconds of frozen window."""
    src = inspect.getsource(am._LiveFeed._make_row)
    assert "tk.Frame" in src and "tk.Label" in src
    assert "ctk." not in src


def test_repaints_are_skipped_when_nothing_changed():
    for fn in (am._LiveFeed.render, am._Stats.show, am._StepBar.set):
        src = inspect.getsource(fn)
        assert "sig" in src or "painted" in src, (
            f"{fn.__qualname__} must not reconfigure widgets blindly")


def test_the_pump_repaints_once_per_batch_not_once_per_event():
    drain = inspect.getsource(am._EventPump.drain)
    assert "_on_flush" in drain
    # the handler runs per event, the repaint runs after the loop
    assert drain.index("self._handler(event)") < drain.index("self._on_flush")


def test_the_live_handler_records_state_and_leaves_drawing_to_the_flush():
    src = inspect.getsource(am.AgentMigratorPage._on_live_event)
    assert "self.live_feed.put(" in src
    assert "render()" not in src
    assert "_paint_live_counts" not in src


def test_command_log_lines_are_buffered_into_one_write():
    log = am._CommandLog
    assert "self._pending.append" in inspect.getsource(log.add)
    assert "configure" not in inspect.getsource(log.add)
    assert "join" in inspect.getsource(log.flush)


def test_a_childless_frame_never_inflates_the_layout():
    """An empty CTkFrame asks for 200x200.

    Used as a grid spacer that was invisible but 200px tall, so a field
    with no button stranded its own helper text half a panel below it,
    and the not-yet-populated stats row left a dead band above the
    results. Needs a display, so it skips rather than fails headless.
    """
    try:
        root = am.ctk.CTk()
    except Exception as exc:                      # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    try:
        form = am._Form(root)
        form.pack(fill="x")
        with_button = form.field("A", "", "helper a",
                                 button=("Go", lambda: None))
        without = form.field("B", "", "helper b")
        stats = am._Stats(root)
        stats.pack(fill="x")
        root.update_idletasks()

        # the two field rows must be the same height as each other
        gap = without.winfo_rooty() - with_button.winfo_rooty()
        assert 0 < gap < 120, (
            f"a field with no button occupies {gap}px; the empty spacer "
            f"frame is inflating the row again")
        assert stats.winfo_reqheight() < 40, (
            f"the stats row reserves {stats.winfo_reqheight()}px before it "
            f"has any tiles")
    finally:
        root.destroy()


def test_a_colour_pair_resolves_to_one_hex_string():
    assert am._hex(("#AAAAAA", "#111111")) in ("#AAAAAA", "#111111")
    assert am._hex("#123456") == "#123456"


# ── wiring guards ───────────────────────────────────────────────────────

def test_every_command_callback_resolves_to_a_real_method():
    """Same guard as tests/test_wiring.py, for the new module."""
    path = os.path.join(ROOT, "agent_migrator.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    failures = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        # Resolve against the real class so inherited widget methods
        # (destroy, lift, …) count, falling back to what's declared here.
        live = getattr(am, cls.name, None)
        methods = set(dir(live)) if live is not None else set()
        methods |= {n.name for n in cls.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        # `self._on_fix = on_fix` is a perfectly good command target too.
        for node in ast.walk(cls):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                methods.add(node.attr)
        for node in ast.walk(cls):
            if not isinstance(node, ast.keyword):
                continue
            if node.arg not in ("command", "callback"):
                continue
            v = node.value
            if (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
                    and v.value.id == "self" and v.attr not in methods):
                failures.append(f"{cls.name}.{v.attr}")
    assert not failures, "missing method: " + ", ".join(failures)


def test_matching_can_never_move_anything():
    """Step 2 only ever builds a plan — it must not reach the mover."""
    src = inspect.getsource(am.AgentMigratorPage._run_match)
    assert "build_match_plan" in src
    assert "run_live_migration" not in src
    assert "move_agents_to_console" not in src


def test_no_dry_run_toggle_survives_anywhere():
    """A single switch deciding whether a run was real was the old design's
    worst foot-gun: forget it and you migrate a console by accident."""
    with open(os.path.join(ROOT, "agent_migrator.py"), encoding="utf-8") as f:
        src = f.read()
    assert "self.dry_run" not in src
    assert "dry_run=self" not in src


def test_the_live_run_is_gated_on_a_match_plan():
    """The old build had one switch deciding whether a run was real; the
    redesign has two separate buttons and step 3 refuses to start until
    step 2 has said what maps where."""
    src = inspect.getsource(am.AgentMigratorPage._run_live)
    assert "if not self._plan" in src
    # it migrates exactly the rows the operator reviewed
    assert 'self._plan["rows"]' in src


def test_the_scheduler_also_refuses_without_a_match_plan():
    src = inspect.getsource(am.AgentMigratorPage._arm)
    assert "if not self._plan" in src


def test_reading_the_destination_again_invalidates_the_old_plan():
    """A new destination file must not leave step 3 armed with counts from
    the previous one."""
    src = inspect.getsource(am.AgentMigratorPage._set_map)
    assert "self._plan = None" in src
    assert "self._report = None" in src


def test_the_runbook_sequences_the_agent_move_after_the_config():
    """Endpoints should only be pointed at a destination that has been
    restored and validated."""
    with open(os.path.join(ROOT, "pages.py"), encoding="utf-8") as f:
        source = f.read()
    steps = source.split("STEPS = [", 1)[1].split("\n    ]", 1)[0]
    order = [s for s in ("Restore to destination", "Validate the migration",
                         "Match the agent scopes", "Migrate the agents",
                         "Manifest & close ticket") if s in steps]
    assert order == ["Restore to destination", "Validate the migration",
                     "Match the agent scopes", "Migrate the agents",
                     "Manifest & close ticket"]
    assert steps.count('"Agent Migration"') == 2
    # …and both are detected from this page rather than ticked by hand
    assert "agents_matched" in source and "agents_moved" in source
    assert '"_plan" if key == "agents_matched" else "_report"' in source


def test_the_page_is_reachable_from_the_migration_nav():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
        source = f.read()
    assert "from agent_migrator import AgentMigratorPage" in source
    nav = source.split("nav_migration = [", 1)[1].split("]", 1)[0]
    assert '("Agent Migration", AgentMigratorPage)' in nav


def test_the_old_flat_token_page_is_gone():
    """It was replaced, not left alongside — one Agent Migration entry."""
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
        app_src = f.read()
    with open(os.path.join(ROOT, "pages.py"), encoding="utf-8") as f:
        pages_src = f.read()
    assert "AgentMigrationPage" not in app_src
    assert "class AgentMigrationPage" not in pages_src
    nav = app_src.split("nav_migration = [", 1)[1].split("]", 1)[0]
    assert nav.count('"Agent Migration"') == 1


def test_the_map_file_round_trips_as_utf8_json(tmp_path):
    data = _map()
    data[0]["sites"][0]["name"] = "Bürö — HQ"
    path = tmp_path / "map.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(path, encoding="utf-8") as f:
        assert json.load(f)[0]["sites"][0]["name"] == "Bürö — HQ"
