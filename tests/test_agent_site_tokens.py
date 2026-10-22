"""Agent migration from a site-token file (agent_migrator.py).

Partners with no API access to the destination send a sheet of site names
and registration tokens instead of a console to read. These tests pin
down that such a file is read whatever shape it arrives in (CSV, TSV,
pasted text, Excel), that every source site is matched to its row by name
and moved with that row's token, and — the part that matters most — that
nothing is ever guessed: a name that matches in two places, a token that
doesn't decode, or a token for the source console itself blocks the site
instead of sending its agents somewhere wrong.

Every token here is synthetic. A real registration token lets anyone
enrol agents into a customer's site, so one must never be committed.
"""
import base64
import hashlib
import inspect
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_migrator as am  # noqa: E402

DEST = "https://euce1-example.sentinelone.net"
SOURCE = "https://beta-example.sentinelone.net"


def tok(name, console=DEST):
    """A synthetic registration token, shaped like the real thing."""
    key = hashlib.sha256(name.encode("utf-8")).hexdigest()
    raw = json.dumps({"url": console, "site_key": key}).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def tsv(*rows, header=("Site Name", "Site Token")):
    return "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"


# The layout the partner actually sent: two tab-separated columns.
FILE = tsv(("Contoso Ltd [CTS]", tok("contoso")),
           ("fabrikam ", tok("fabrikam")),        # case and a stray space
           ("Tailspin Toys", tok("tailspin")),
           ("Adventure Works", tok("adventure")))


# ── a fake source console ───────────────────────────────────────────────

def agents(prefix, n):
    return [{"id": f"{prefix}-{i}", "computerName": f"{prefix.upper()}-{i}",
             "osName": "Windows 11", "isActive": True}
            for i in range(1, n + 1)]


class Source:
    """Accounts → sites → groups → agents, answering like the console."""

    def __init__(self, accounts, base_url=SOURCE):
        self.base_url = base_url
        self.accounts = accounts
        self.moves = []

    def _account(self, account_id):
        return next((a for a in self.accounts
                     if a["id"] == str(account_id)), None)

    def _groups(self):
        for acct in self.accounts:
            for site in acct["sites"]:
                yield from site["groups"]

    def get_accounts(self, **kw):
        return [{"id": a["id"], "name": a["name"]} for a in self.accounts]

    def get_account_by_id(self, account_id):
        acct = self._account(account_id)
        return {"id": acct["id"], "name": acct["name"]} if acct else None

    def get_sites(self, params=None, **kw):
        params = params or {}
        acct = self._account(params.get("accountId", "")) or {"sites": []}
        want = set(am.split_ids(params.get("siteIds", "")))
        return [{"id": s["id"], "name": s["name"]} for s in acct["sites"]
                if not want or s["id"] in want]

    def get_groups(self, params=None, **kw):
        sid = str((params or {}).get("siteIds", ""))
        for acct in self.accounts:
            for site in acct["sites"]:
                if site["id"] == sid:
                    return [{"id": g["id"], "name": g["name"],
                             "totalAgents": len(g["agents"])}
                            for g in site["groups"]]
        return []

    def get_agents(self, params=None, **kw):
        params = dict(params or {})
        if "ids" in params:                       # the post-move read-back
            wanted = set(str(params["ids"]).split(","))
            return [dict(a, consoleMigrationStatus="Migrated")
                    for g in self._groups() for a in g["agents"]
                    if a["id"] in wanted]
        gid = str(params.get("groupIds", ""))
        rows = [dict(a) for g in self._groups() if g["id"] == gid
                for a in g["agents"]]
        if params.get("consoleMigrationStatusesNin") == "Migrated":
            rows = [a for a in rows
                    if a.get("consoleMigrationStatus") != "Migrated"]
        return rows

    def move_agents_to_console(self, agent_ids, token, extra_filter=None):
        self.moves.append({"ids": list(agent_ids), "token": token,
                           "filter": dict(extra_filter or {})})
        return {"data": {"affected": len(agent_ids)}}


def msp():
    """One MSP account on the source, a customer per site."""
    return Source([{
        "id": "100", "name": "Northwind MSP",
        "sites": [
            {"id": "S1", "name": "Contoso Ltd [CTS]", "groups": [
                {"id": "G1", "name": "Default Group",
                 "agents": agents("cts", 2)},
                {"id": "G2", "name": "Servers", "agents": agents("srv", 1)}]},
            {"id": "S2", "name": "Fabrikam", "groups": [
                {"id": "G3", "name": "Default Group",
                 "agents": agents("fab", 1)}]},
            {"id": "S3", "name": "Tailspin Toys", "groups": [
                {"id": "G4", "name": "Default Group", "agents": []}]},
            {"id": "S4", "name": "Wingtip", "groups": [
                {"id": "G5", "name": "Default Group",
                 "agents": agents("wtp", 3)}]},
        ]}])


def shira():
    """One account whose site the partner's file spells differently."""
    return Source([{
        "id": "100", "name": "20075 - Mirage IT",
        "sites": [
            {"id": "S7", "name": "Shira Telecom", "groups": [
                {"id": "G7", "name": "Default Group",
                 "agents": agents("shr", 4)}]},
            {"id": "S8", "name": "Contoso", "groups": [
                {"id": "G8", "name": "Default Group",
                 "agents": agents("cts", 1)}]},
        ]}])


SHIRA_FILE = tsv(("Contoso", tok("contoso")), ("shira-telecom", tok("shira")))


def two_msps():
    """Two accounts that both have a site called "Default site"."""
    def one(aid, name, sid, gid, prefix, n):
        return {"id": aid, "name": name, "sites": [
            {"id": sid, "name": "Default site", "groups": [
                {"id": gid, "name": "Default Group",
                 "agents": agents(prefix, n)}]}]}
    return Source([one("100", "Northwind MSP", "S1", "G1", "nw", 2),
                   one("200", "Litware MSP", "S9", "G9", "lw", 5)])


# ── reading a token ─────────────────────────────────────────────────────

def test_a_token_says_which_console_it_belongs_to():
    t = tok("x")
    info = am.decode_token(t)
    assert info["url"] == DEST and len(info["site_key"]) == 64
    assert am.decode_token(t.rstrip("=")) == info          # padding lost
    assert am.decode_token(f" {t[:40]}\n {t[40:]} ") == info  # wrapped cell
    assert am.decode_token("not a token") == {}
    assert am.decode_token("") == {}
    assert am.decode_token(base64.b64encode(b'"text"').decode()) == {}


def test_the_screen_only_ever_shows_a_hint_of_a_token():
    t = tok("x")
    hint = am.token_hint(t)
    assert hint.startswith("key …")
    assert hint.endswith(am.decode_token(t)["site_key"][-6:])
    assert t not in hint
    assert am.console_host(DEST + "/dashboard") == "euce1-example"
    assert am.console_host("") == ""


# ── reading the file, whatever shape it is in ───────────────────────────

def test_the_partners_two_column_layout_is_read():
    data = am.parse_site_tokens_text(FILE)
    assert [e["source"] for e in data["entries"]] == [
        "Contoso Ltd [CTS]", "fabrikam", "Tailspin Toys", "Adventure Works"]
    assert all(e["problem"] == "" for e in data["entries"])
    assert data["consoles"] == [DEST]
    first = data["entries"][0]
    assert first["row"] == 2                    # row numbers match the file
    assert first["dest"] == "Contoso Ltd [CTS]"
    assert first["token"] == tok("contoso")


def test_a_csv_with_a_bom_quotes_and_separate_source_and_destination(tmp_path):
    path = tmp_path / "tokens.csv"
    path.write_text("Source Site,Destination Site,Registration Token\n"
                    f'"Contoso, Ltd",Contoso (new),{tok("c")}\n',
                    encoding="utf-8-sig")
    entry = am.read_site_tokens(str(path))["entries"][0]
    assert (entry["source"], entry["dest"]) == ("Contoso, Ltd",
                                                "Contoso (new)")
    assert entry["token"] == tok("c") and not entry["problem"]
    assert am.file_destination(entry) == "Contoso (new)  ·  euce1-example"


def test_excel_unicode_text_and_windows_csv_are_both_decoded(tmp_path):
    unicode_text = tmp_path / "unicode.txt"
    unicode_text.write_bytes(
        f"Site Name\tSite Token\r\nCafé Olé\t{tok('cafe')}\r\n"
        .encode("utf-16"))
    assert am.read_site_tokens(str(unicode_text))["entries"][0][
        "source"] == "Café Olé"
    windows = tmp_path / "windows.csv"
    windows.write_bytes(
        f"Site Name,Site Token\r\nCafé Olé,{tok('cafe')}\r\n"
        .encode("cp1252"))
    assert am.read_site_tokens(str(windows))["entries"][0][
        "source"] == "Café Olé"


def test_a_workbook_is_read_from_whichever_sheet_holds_the_table(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Notes"
    book.active.append(["Northwind migration — read me first"])
    sheet = book.create_sheet("Tokens")
    sheet.append(["Site tokens for the new console"])      # a title row
    sheet.append([])
    sheet.append(["Site Name", "Site Token"])
    sheet.append(["Contoso Ltd [CTS]", tok("contoso")])
    sheet.append(["Fabrikam", tok("fabrikam")])
    path = tmp_path / "SiteTokens.xlsx"
    book.save(path)

    data = am.read_site_tokens(str(path))
    assert [e["source"] for e in data["entries"]] == ["Contoso Ltd [CTS]",
                                                      "Fabrikam"]
    assert [e["row"] for e in data["entries"]] == [4, 5]   # Excel's rows
    assert data["source"] == str(path)


def test_unreadable_files_are_refused_with_a_reason(tmp_path):
    with pytest.raises(ValueError, match="xlsx"):
        am.read_site_tokens(str(tmp_path / "old.xls"))
    with pytest.raises(ValueError, match="Site Token"):
        am.parse_site_tokens_text("Site Name,Owner\nContoso,Alice\n")
    with pytest.raises(ValueError, match="no site rows"):
        am.parse_site_tokens_text("Site Name\tSite Token\n")


def test_a_sheet_without_a_header_works_when_one_column_is_all_tokens():
    data = am.parse_site_tokens_text(
        f"Contoso\t{tok('c')}\nFabrikam\t{tok('f')}\n")
    assert data["headless"] is True
    assert [e["source"] for e in data["entries"]] == ["Contoso", "Fabrikam"]


def test_text_pasted_from_an_email_that_lost_its_tabs():
    text = (f"Site Name Site Token\n"
            f"Contoso Ltd [CTS]   {tok('c')}\n"
            f"Proseware (PSW) {tok('p')}\n")
    data = am.parse_site_tokens_text(text)
    assert [(e["source"], e["token"]) for e in data["entries"]] == [
        ("Contoso Ltd [CTS]", tok("c")), ("Proseware (PSW)", tok("p"))]


def test_every_row_is_checked_before_any_console_is_asked():
    data = am.parse_site_tokens_text(tsv(
        ("Contoso", tok("c")),
        ("Fabrikam", "not-a-token"),
        ("Tailspin", ""),
        ("Contoso", tok("c")),           # the same row twice: harmless
        ("Wingtip", tok("w1")),
        ("wingtip", tok("w2")),          # the same site, another token
        ("", tok("orphan")),             # a token with no site
    ))
    by = {e["source"]: e for e in data["entries"]}
    assert set(by) == {"Contoso", "Fabrikam", "Tailspin", "Wingtip"}
    assert by["Contoso"]["problem"] == ""
    assert "does not decode" in by["Fabrikam"]["problem"]
    assert by["Tailspin"]["problem"] == "no token in the file"
    assert "different tokens (rows 6, 7)" in by["Wingtip"]["problem"]
    assert {s["row"]: s["reason"] for s in data["skipped"]} == {
        5: "repeats row 2", 7: "repeats row 6", 8: "no site name"}


def test_a_token_broken_across_lines_in_a_cell_is_rejoined():
    t = tok("c")
    data = am.parse_site_tokens([["Site Name", "Site Token"],
                                 ["Contoso", f"{t[:50]}\n {t[50:]}"]])
    entry = data["entries"][0]
    assert entry["token"] == t and not entry["problem"]


def test_a_group_column_is_never_taken_for_the_site_name():
    data = am.parse_site_tokens([["Group Name", "Site Name", "Site Token"],
                                 ["Laptops", "Contoso", tok("c")]])
    assert data["entries"][0]["source"] == "Contoso"


def test_one_site_name_may_appear_once_per_source_account():
    data = am.parse_site_tokens([
        ["Source Account", "Site Name", "Site Token"],
        ["Northwind MSP", "Default site", tok("a")],
        ["Litware MSP", "Default site", tok("b")]])
    assert [(e["account"], e["source"]) for e in data["entries"]] == [
        ("Northwind MSP", "Default site"), ("Litware MSP", "Default site")]
    assert not any(e["problem"] for e in data["entries"])


# ── matching the source against the file ────────────────────────────────

def test_each_source_site_moves_with_its_own_rows_token():
    api = msp()
    plan = am.build_file_plan(api, am.parse_site_tokens_text(FILE), "100",
                              source_url=SOURCE)
    ready = [r for r in plan["rows"] if r["state"] == "ready"]
    assert [(r["Site"], r["Group"], r["Agents"]) for r in ready] == [
        ("Contoso Ltd [CTS]", "Default Group", 2),
        ("Contoso Ltd [CTS]", "Servers", 1),
        ("Fabrikam", "Default Group", 1)]
    assert ready[0]["Destination"] == "Contoso Ltd [CTS]  ·  euce1-example"
    assert plan["mode"] == "file"
    assert plan["agents"] == 4 and plan["ready"] == 3
    assert api.moves == []                         # matching sends nothing

    run = am.run_live_migration(api, plan["rows"], verify=False)
    assert {m["filter"]["groupIds"][0]: m["token"] for m in api.moves} == {
        "G1": tok("contoso"), "G2": tok("contoso"), "G3": tok("fabrikam")}
    assert run["sent"] == 4 and run["errors"] == []


def test_what_cannot_move_is_named_with_the_reason():
    plan = am.build_file_plan(msp(), am.parse_site_tokens_text(FILE), "100")
    others = {r["Site"]: r for r in plan["rows"] if r["state"] != "ready"}

    wingtip = others["Wingtip"]
    assert wingtip["Status"] == am.NOT_IN_FILE and wingtip["kind"] == "site"
    assert wingtip["Total"] == 3 and "stay put" in wingtip["reason"]
    tailspin = others["Tailspin Toys"]
    assert tailspin["state"] == "done"
    assert tailspin["Status"] == am.NOTHING_TO_MOVE
    adventure = others["Adventure Works"]
    assert adventure["Status"] == am.NOT_ON_SOURCE
    assert adventure["kind"] == "file" and "Row 5" in adventure["reason"]

    assert [u["site"] for u in plan["unlisted"]] == ["Wingtip"]
    assert [e["source"] for e in plan["unused"]] == ["Adventure Works"]
    assert plan["blocked"] == 2 and plan["done"] == 1


def test_a_near_miss_is_suggested_but_never_taken():
    api = msp()
    plan = am.build_file_plan(
        api, am.parse_site_tokens_text(tsv(("Wingtip Inc", tok("w")))), "100")
    row = next(r for r in plan["rows"] if r["Site"] == "Wingtip Inc")
    assert row["Status"] == am.NOT_ON_SOURCE and "'Wingtip'" in row["reason"]
    assert plan["ready"] == 0
    am.run_live_migration(api, plan["rows"], verify=False)
    assert api.moves == []


def test_pairing_by_hand_turns_a_near_miss_into_a_match():
    api = msp()
    data = am.parse_site_tokens_text(tsv(("Wingtip Inc", tok("w"))))
    plan = am.build_file_plan(api, data, "100")
    wingtip = next(u for u in plan["unlisted"] if u["site"] == "Wingtip")
    # the closest name is offered first
    assert am.rank_sites_by_name("Wingtip Inc", plan["unlisted"])[0] is wingtip

    assert am.pair_file_rows([(plan["unused"][0], wingtip)]) == 1
    again = am.build_file_plan(api, data, "100")
    row = next(r for r in again["rows"] if r["Site"] == "Wingtip")
    assert row["state"] == "ready" and row["token"] == tok("w")
    # …and it still lands where the file says
    assert row["Destination"].startswith("Wingtip Inc")
    assert again["unused"] == []
    assert data["entries"][0]["paired"] is True


def test_the_same_name_spelt_differently_is_offered_first():
    assert am.loose_name("shira-telecom") == "shira telecom"
    assert am.loose_name("Shira_Telecom (IL)") == "shira telecom il"
    rows = am.parse_site_tokens_text(tsv(
        ("Shiraz Telco", tok("z")), ("Telecom Shira", tok("t")),
        ("shira-telecom", tok("s"))))["entries"]
    ranked = am.rank_file_rows("Shira Telecom", rows)
    assert ranked[0]["source"] == "shira-telecom"
    # matching itself stays exact: nothing is paired by the loose name
    plan = am.build_file_plan(shira(), am.parse_site_tokens_text(SHIRA_FILE),
                              "100", site_id="S7")
    assert plan["ready"] == 0


def test_a_chosen_site_spelt_differently_in_the_file_can_be_paired():
    """One site chosen in step 1, and the file calls it 'shira-telecom':
    the file's other rows aren't reported as missing, but they are still
    offered — and the one spelt differently is named in the reason."""
    api = shira()
    data = am.parse_site_tokens_text(SHIRA_FILE)
    plan = am.build_file_plan(api, data, "100", site_id="S7")
    (row,) = plan["rows"]
    assert row["Status"] == am.NOT_IN_FILE
    assert ("Row 3 of the file, 'shira-telecom', is the same name spelt "
            "differently") in row["reason"]
    assert plan["unused"] == []
    assert [e["source"] for e in plan["spare"]] == ["Contoso",
                                                    "shira-telecom"]
    rows = am.AgentMigratorPage._pair_rows(plan)
    assert rows == plan["spare"]

    site = plan["unlisted"][0]
    entry = am.rank_file_rows(site["site"], rows)[0]
    assert am.pair_file_rows([(entry, site)]) == 1
    again = am.build_file_plan(api, data, "100", site_id="S7")
    ready = [r for r in again["rows"] if r["state"] == "ready"]
    assert [(r["Group"], r["token"]) for r in ready] == [
        ("Default Group", tok("shira"))]
    # …and it lands where the file says
    assert ready[0]["Destination"].startswith("shira-telecom")
    assert api.moves == []


def test_the_hint_names_the_closest_row_nothing_uses():
    rows = am.parse_site_tokens_text(tsv(
        ("Shira Telecom Ltd", tok("s")), ("Zeta", tok("z"))))["entries"]
    assert ("closest row of the file nothing uses is 'Shira Telecom Ltd' "
            "(row 2)") in am._row_hint("Shira Telecom", rows)
    assert "If the file names it differently" in am._row_hint("Qwerty", rows)
    assert am._row_hint("Shira Telecom", []) == ""
    pinned = am.parse_site_tokens([
        ["Source Account", "Site Name", "Site Token"],
        ["Litware MSP", "Shira Telecom", tok("s")]])["entries"]
    assert "names it for the account 'Litware MSP'" in am._row_hint(
        "Shira Telecom", pinned)


def test_only_rows_that_pairing_could_fix_offer_it():
    plan = am.build_file_plan(msp(), am.parse_site_tokens_text(tsv(
        ("Wingtip Inc", tok("w")), ("Proseware", "not-a-token"))), "100")
    kinds = {r["Site"]: r["kind"] for r in plan["rows"]
             if r["Status"] == am.NOT_ON_SOURCE}
    assert kinds == {"Wingtip Inc": "file", "Proseware": ""}
    pairable = am.AgentMigratorPage._pairable(plan["unused"])
    assert [e["source"] for e in pairable] == ["Wingtip Inc"]


def test_a_name_in_two_accounts_is_refused_not_guessed():
    """"Default site" exists in every account. Picking one would hand a
    customer's agents to another customer's site."""
    api = two_msps()
    data = am.parse_site_tokens_text(tsv(("Default site", tok("d"))))
    plan = am.build_file_plan(api, data, "")
    assert plan["ready"] == 0
    assert [r["Status"] for r in plan["rows"]] == [am.AMBIGUOUS, am.AMBIGUOUS]
    assert "Source Account" in plan["rows"][0]["reason"]
    am.run_live_migration(api, plan["rows"], verify=False)
    assert api.moves == []

    # naming the one source account settles it
    narrowed = am.build_file_plan(api, data, "200")
    assert [r["group_id"] for r in narrowed["rows"]
            if r["state"] == "ready"] == ["G9"]


def test_a_source_account_column_settles_which_site_is_meant():
    api = two_msps()
    data = am.parse_site_tokens([
        ["Source Account", "Site Name", "Site Token"],
        ["Litware MSP", "Default site", tok("d")]])
    plan = am.build_file_plan(api, data, "")
    ready = [r for r in plan["rows"] if r["state"] == "ready"]
    assert [(r["Account"], r["group_id"]) for r in ready] == [
        ("Litware MSP", "G9")]
    # Northwind has nothing in the file, so it stays out of the plan
    assert all(r["Account"] != "Northwind MSP" for r in plan["rows"])
    assert plan["quiet_accounts"] == 1


def test_with_no_account_named_only_the_files_accounts_are_in_play():
    api = msp()
    api.accounts.append({"id": "300", "name": "Unrelated Co", "sites": [
        {"id": "U1", "name": "HQ", "groups": [
            {"id": "UG1", "name": "Default Group",
             "agents": agents("hq", 4)}]}]})
    plan = am.build_file_plan(api, am.parse_site_tokens_text(FILE), "")
    assert all(r["Account"] != "Unrelated Co" for r in plan["rows"])
    assert plan["quiet_accounts"] == 1
    # the MSP's own gap is still shown
    assert [u["site"] for u in plan["unlisted"]] == ["Wingtip"]


def test_a_token_for_the_source_console_moves_nothing():
    plan = am.build_file_plan(
        msp(), am.parse_site_tokens_text(
            tsv(("Fabrikam", tok("f", console=SOURCE)))),
        "100", source_url=SOURCE + "/dashboard")
    row = next(r for r in plan["rows"] if r["Site"] == "Fabrikam")
    assert row["state"] == "blocked" and row["Status"] == am.SAME_CONSOLE


def test_a_row_with_a_bad_or_missing_token_blocks_its_site():
    plan = am.build_file_plan(msp(), am.parse_site_tokens_text(tsv(
        ("Fabrikam", "not-a-token"), ("Contoso Ltd [CTS]", ""))), "100")
    by_site = {r["Site"]: r for r in plan["rows"]}
    assert by_site["Fabrikam"]["Status"] == am.FILE_PROBLEM
    assert "row 2" in by_site["Fabrikam"]["reason"]
    assert by_site["Contoso Ltd [CTS]"]["Status"] == am.FILE_PROBLEM
    assert plan["ready"] == 0


def test_groups_whose_agents_already_moved_are_done():
    api = msp()
    for agent in api.accounts[0]["sites"][0]["groups"][1]["agents"]:
        agent["consoleMigrationStatus"] = "Migrated"        # Contoso/Servers
    plan = am.build_file_plan(api, am.parse_site_tokens_text(FILE), "100")
    servers = next(r for r in plan["rows"] if r["Group"] == "Servers")
    assert servers["state"] == "done" and servers["Status"] == am.ALL_DONE
    assert plan["agents"] == 3


def test_a_site_filter_does_not_report_the_rest_of_the_file_as_missing():
    said = []
    plan = am.build_file_plan(msp(), am.parse_site_tokens_text(FILE), "100",
                              site_id="S2", log=said.append)
    assert [r["Site"] for r in plan["rows"]] == ["Fabrikam"]
    assert plan["unused"] == []
    assert any("outside the chosen sites" in m for m in said)
    # not reported — but still there to pair a chosen site with
    assert [e["source"] for e in plan["spare"]] == [
        "Contoso Ltd [CTS]", "Tailspin Toys", "Adventure Works"]


def test_stopping_early_reports_nothing_as_missing():
    plan = am.build_file_plan(msp(), am.parse_site_tokens_text(FILE), "100",
                              should_stop=lambda: True)
    assert plan["stopped"] is True
    assert plan["rows"] == [] and plan["unused"] == []


def test_tokens_never_reach_the_log_or_the_reports():
    api = msp()
    data = am.parse_site_tokens_text(FILE)
    secrets = [e["token"] for e in data["entries"]]
    said, events = [], []
    plan = am.build_file_plan(api, data, "100", log=said.append)
    blob = json.dumps({"log": said, "summary": am.plan_summary_text(plan),
                       "report": am.build_match_report(plan, "tokens.csv")},
                      default=str)
    assert not any(s in blob for s in secrets)

    run = am.run_live_migration(api, plan["rows"], on_event=events.append,
                                verify=False)
    requests = [e for e in events if e["type"] == "request"]
    assert requests and all(e["token"].startswith("…") for e in requests)
    live = json.dumps(am.build_live_report(run), default=str)
    assert not any(s in live for s in secrets)


def test_the_reports_say_where_the_tokens_came_from():
    plan = am.build_file_plan(
        msp(), am.parse_site_tokens_text(FILE, source="SiteTokens.xlsx"),
        "100")
    info = dict(am.build_match_report(plan, plan["file"])["info"])
    assert info["Site-token file"] == "SiteTokens.xlsx"
    assert info["Source sites not in the file"] == 1
    assert info["File rows with no source site"] == 1
    text = am.plan_summary_text(plan)
    assert "Tokens from:        SiteTokens.xlsx" in text
    assert "Sites not in file:  1" in text
    live = am.build_live_report({}, map_path="SiteTokens.xlsx",
                                map_label="Site-token file")
    assert ("Site-token file", "SiteTokens.xlsx") in live["info"]


# ── the page: wiring guards ─────────────────────────────────────────────

def test_step_two_plans_from_either_kind_of_token_and_never_moves():
    src = inspect.getsource(am.AgentMigratorPage._run_match)
    assert "build_file_plan" in src and "build_match_plan" in src
    assert "run_live_migration" not in src
    assert "move_agents_to_console" not in src


def test_a_new_file_or_a_switch_of_token_source_forgets_the_plan():
    forget = inspect.getsource(am.AgentMigratorPage._forget_plan_view)
    assert "self._plan = None" in forget and "self._report = None" in forget
    for fn in (am.AgentMigratorPage._set_site_tokens,
               am.AgentMigratorPage._on_dest_mode,
               am.AgentMigratorPage._after_pair):
        assert "self._forget_plan_view()" in inspect.getsource(fn), (
            f"{fn.__name__} must not leave step 3 armed with an old plan")


def test_file_plans_are_not_cached_against_a_map():
    src = inspect.getsource(am.AgentMigratorPage._remember_plan)
    assert 'plan.get("mode") == "file"' in src


def test_step_two_unlocks_on_whichever_step_one_was_used():
    for fn in (am.AgentMigratorPage._refresh_gates,
               am.AgentMigratorPage._run_match):
        assert "self._dest_ready()" in inspect.getsource(fn)


# ── the page itself (needs a display) ───────────────────────────────────

class _StubApp:
    source_api = None
    dest_api = None

    def __init__(self):
        self.lines, self.audit = [], []

    def cli_log(self, msg, level="info"):
        self.lines.append(msg)

    def log_audit(self, action, **fields):
        self.audit.append((action, fields))


@pytest.fixture
def page(monkeypatch, tmp_path):
    monkeypatch.setattr(am.config, "CONFIG_DIR", str(tmp_path))
    try:
        root = am.ctk.CTk()
    except Exception as exc:                      # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    app = _StubApp()
    pg = am.AgentMigratorPage(root, app)
    pg.grid(row=0, column=0, sticky="nsew")
    try:
        yield pg, app
    finally:
        root.destroy()


def _settle(page, until, timeout=10.0):
    """Run the Tk main loop until `until()` holds (the worker reports back
    with after(), which needs the main thread inside mainloop)."""
    deadline = time.monotonic() + timeout

    def poll():
        if until() or time.monotonic() > deadline:
            page.quit()
        else:
            page.after(20, poll)

    page.after(20, poll)
    page.mainloop()
    assert until(), "the page never finished"


def test_a_loaded_file_unlocks_matching_with_no_destination_connected(page):
    pg, app = page
    app.source_api = msp()                       # the source is connected
    pg.dest_switch.set(pg.MODE_FILE)
    pg._on_dest_mode(pg.MODE_FILE)
    assert pg.cards[1].step_state == "locked"   # …but nothing says where to

    pg._set_site_tokens(am.parse_site_tokens_text(
        FILE, source="/tmp/SiteTokens.csv"))
    assert pg._dest_ready()
    assert pg.cards[0].step_state == "done"
    assert pg.cards[1].step_state != "locked"
    assert pg.check_btn.cget("state") == "normal"
    assert pg._dest_name() == "euce1-example"
    action, fields = app.audit[-1]
    assert action == "agent_site_tokens_loaded" and fields["sites"] == 4
    assert not any(e["token"] in json.dumps(app.audit)
                   for e in pg._site_tokens["entries"])

    # back to reading the console: none connected, so step 2 locks again
    pg._on_dest_mode(pg.MODE_CONSOLE)
    assert pg.cards[1].step_state == "locked" and pg._plan is None


def _view(table):
    table.counts()
    return [table._records[k]["entry"]["source"] for k in table._view]


def test_the_pairing_dialog_starts_every_site_unpaired(page):
    pg, _app = page
    sites = [{"account": "Northwind MSP", "account_id": "100",
              "site": "Shira Telecom", "site_id": "S7", "agents": 4},
             {"account": "Northwind MSP", "account_id": "100",
              "site": "Wingtip", "site_id": "S4", "agents": 3}]
    rows = am.parse_site_tokens_text(tsv(
        ("Wingtip Inc", tok("w")), ("shira-telecom", tok("s")),
        ("Zeta", tok("z"))))["entries"]
    got = []
    dlg = am._SitePairDialog(pg, sites, rows, got.append)
    try:
        # nothing is paired by itself — the same name spelt differently is
        # first, and selected for a look
        assert dlg._picks == {} and dlg._current == 0
        assert _view(dlg.row_list)[0] == "shira-telecom"
        assert dlg._row is rows[1]
        assert dlg._use_btn.cget("text") == "Use row 3 for “Shira Telecom”"
        assert dlg._apply_btn.cget("state") == "disabled"

        dlg._use()
        assert dlg._picks == {0: rows[1]} and dlg._current == 1
        # Wingtip has no same-named row, so nothing is selected for it
        assert dlg._row is None
        assert _view(dlg.row_list)[0] == "Wingtip Inc"

        # a row's token goes to one site
        dlg._on_row(dlg.row_list._records[3])
        assert dlg._use_btn.cget("state") == "disabled"
        assert "already your pick for “Shira Telecom”" in \
            dlg._note.cget("text")
        dlg._use()
        assert 1 not in dlg._picks

        # search, and Return uses the one row left
        dlg._search.insert(0, "wingtip")
        dlg._filter_rows()
        assert _view(dlg.row_list) == ["Wingtip Inc"]
        dlg._use_only()
        assert dlg._picks[1] is rows[0]
        assert dlg._apply_btn.cget("text") == "Pair 2 sites & check again"
        dlg._apply()
    finally:
        if dlg.winfo_exists():
            dlg.destroy()
    assert got == [[(rows[1], sites[0]), (rows[0], sites[1])]]


def test_a_chosen_site_is_paired_and_migrated_from_the_page(page, monkeypatch):
    pg, app = page
    api = shira()
    app.source_api = api
    monkeypatch.setattr(am.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(am.messagebox, "showinfo", lambda *a, **k: None)
    made = []
    real = am._SitePairDialog

    def keep(*a, **k):
        made.append(real(*a, **k))
        return made[-1]
    monkeypatch.setattr(am, "_SitePairDialog", keep)
    pg.dest_switch.set(pg.MODE_FILE)
    pg._on_dest_mode(pg.MODE_FILE)
    pg._set_site_tokens(am.parse_site_tokens_text(
        SHIRA_FILE, source="/tmp/SiteTokens.xlsx"))
    pg.src_accounts.insert(0, "100")
    pg.src_sites.insert(0, "S7")

    pg._run_match()
    _settle(pg, lambda: pg._busy is None)
    assert pg._plan["ready"] == 0 and pg._fixable()
    pg._refresh_gates()
    assert pg.fix_btn.winfo_manager()
    assert pg.fix_btn.cget("text") == "✎  Pair sites"
    assert pg._fix_tip.text == pg.PAIR_TIP

    pg._fix_names()
    (dlg,) = made
    assert dlg._row["source"] == "shira-telecom"
    dlg._use()
    dlg._apply()
    _settle(pg, lambda: pg._busy is None)
    assert pg._plan["ready"] == 1 and pg._plan["agents"] == 4
    assert not pg._fixable()
    assert api.moves == []                       # pairing sent nothing

    pg._run_live()
    _settle(pg, lambda: pg._busy is None)
    assert {m["filter"]["groupIds"][0]: m["token"] for m in api.moves} == {
        "G7": tok("shira")}


def test_a_file_checks_and_migrates_from_the_page(page, monkeypatch):
    pg, app = page
    api = msp()
    app.source_api = api
    monkeypatch.setattr(am.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(am.messagebox, "showinfo", lambda *a, **k: None)
    pg.dest_switch.set(pg.MODE_FILE)
    pg._on_dest_mode(pg.MODE_FILE)
    pg._set_site_tokens(am.parse_site_tokens_text(
        FILE, source="/tmp/SiteTokens.csv"))
    pg.src_accounts.insert(0, "100")

    pg._run_match()
    _settle(pg, lambda: pg._busy is None)
    assert pg._plan["mode"] == "file" and pg._plan["ready"] == 3
    assert api.moves == []                       # the check sent nothing
    assert pg._fixable()          # Adventure Works ↔ Wingtip can be paired
    assert pg.live_btn.cget("state") == "normal"

    pg._run_live()
    _settle(pg, lambda: pg._busy is None)
    assert {m["filter"]["groupIds"][0]: m["token"] for m in api.moves} == {
        "G1": tok("contoso"), "G2": tok("contoso"), "G3": tok("fabrikam")}
    assert pg._report["moved"] == 4
    label, value = pg._dest_source()
    assert (label, value) == ("Site-token file", "/tmp/SiteTokens.csv")

    # a new file throws the plan and the run away
    pg._set_site_tokens(am.parse_site_tokens_text(FILE, source="again.csv"))
    assert pg._plan is None and pg._report is None
    assert pg.live_btn.cget("state") == "disabled"
