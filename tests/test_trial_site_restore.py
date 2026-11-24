import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import RestorePage, _dest_site_type, _failure_counts
from s1_api import S1APIError

ACCT = "Grupo Damm"
TRIAL_REJECTION = ("Validation Error :: Cannot create a paid Site where "
                   "Account is trial (code 4000010)")
SITES_AND_GROUPS = {"global": False, "accounts": False,
                    "sites": True, "groups": True}


class _Widget:
    def __getattr__(self, _name):
        return lambda *a, **kw: None


class Console:
    base_url = "https://euce1-111.sentinelone.net"

    def __init__(self, account_type="Trial", refuse_sites=""):
        self.account = {"id": "A1", "name": ACCT,
                        "accountType": account_type}
        self.sites = [{"id": "S0", "name": "Default site",
                       "isDefault": True, "state": "active"}]
        self.groups = []
        self.site_posts = []
        self.refuse_sites = refuse_sites

    def get_accounts(self, **_kw):
        return [dict(self.account)]

    def get_sites(self, params=None):
        return [dict(s) for s in self.sites]

    def get_groups(self, params=None):
        site_id = (params or {}).get("siteIds")
        return [dict(g) for g in self.groups if g["siteId"] == site_id]

    def create_site(self, account_id, data):
        self.site_posts.append(dict(data))
        if self.refuse_sites:
            raise S1APIError("POST /sites → 400", status_code=400,
                             detail=self.refuse_sites)
        if (self.account["accountType"] == "Trial"
                and data.get("siteType") == "Paid"):
            raise S1APIError("POST /sites → 400", status_code=400,
                             detail=TRIAL_REJECTION)
        site = {"id": f"S{len(self.sites)}", "name": data["name"],
                "isDefault": False, "state": "active"}
        self.sites.append(site)
        return {"data": dict(site)}

    def create_group(self, site_id, data):
        group = dict(data, id=f"G{len(self.groups) + 1}", siteId=site_id)
        self.groups.append(group)
        return {"data": dict(group)}

    def __getattr__(self, _name):
        return lambda *a, **kw: {}


class Runner:
    _run_restore = RestorePage._run_restore
    _resolve_dest_id = RestorePage._resolve_dest_id
    _ledger_add = RestorePage._ledger_add
    _record_site_element = RestorePage._record_site_element
    _set_skip_label = RestorePage._set_skip_label

    def __init__(self):
        self.ptable = _Widget()
        self.progress = _Widget()
        self.log = _Widget()
        self._skip_btn = _Widget()
        self._status_lbl = _Widget()
        self._operation_log = []
        self._item_ledger = []
        self._report_nodes = []
        self._resolve_issues = {}
        self._resolved_site_ids = {}
        self._skip_make_default_ids = set()
        self._checkpoint = {}
        self._cancelled = False
        self._skip_element = False
        self._acct_id = ""
        self._auto_create_accounts = False
        self._auto_mode = True

    def after(self, _delay, fn=None):
        if fn is not None:
            fn()

    def _rerank_groups(self, api, nodes):
        return None


def _site(name, default=False):
    return {"type": "site", "path": f"{ACCT}/{name}",
            "site": {"name": name, "siteType": "Paid", "suite": "Complete",
                     "sku": "Complete", "isDefault": default,
                     "state": "active"},
            "data": {}}


def _group(site, name):
    return {"type": "group", "path": f"{ACCT}/{site}/{name}",
            "group": {"name": name, "type": "static"}, "data": {}}


def _restore(console):
    runner = Runner()
    backup = [_site("Default site", default=True), _site("OT"),
              _group("OT", "LAPTOPS")]
    runner._run_restore(console, backup, [], levels=SITES_AND_GROUPS)
    return runner


def test_a_trial_account_only_gets_trial_sites():
    assert _dest_site_type("Paid", {"accountType": "Trial"}) == "Trial"
    assert _dest_site_type("Paid", {"accountType": "trial"}) == "Trial"


def test_a_paid_account_keeps_the_source_site_type():
    assert _dest_site_type("Paid", {"accountType": "Paid"}) == "Paid"
    assert _dest_site_type("Trial", {"accountType": "Paid"}) == "Trial"


def test_an_unknown_account_type_keeps_the_source_site_type():
    assert _dest_site_type("Paid", {}) == "Paid"
    assert _dest_site_type(None, None) == ""


def test_restoring_into_a_trial_account_creates_the_sites_and_groups():
    console = Console("Trial")
    runner = _restore(console)
    assert [p.get("siteType") for p in console.site_posts] == ["Trial"]
    assert [(g["name"], g["siteId"]) for g in console.groups] == \
        [("LAPTOPS", console.sites[-1]["id"])]
    assert _failure_counts(runner._report_nodes) == (0, 0)


def test_the_log_says_why_the_site_type_changed():
    runner = _restore(Console("Trial"))
    assert any("creating 'OT' as a Trial site" in line
               for line in runner._operation_log)


def test_a_paid_account_still_gets_paid_sites():
    console = Console("Paid")
    runner = _restore(console)
    assert [p.get("siteType") for p in console.site_posts] == ["Paid"]
    assert not any("as a Trial site" in line
                   for line in runner._operation_log)


def test_scopes_the_destination_refuses_are_counted_as_failures():
    runner = _restore(Console("Paid", refuse_sites="License limit reached"))
    failed = {n["path"]: n for n in runner._report_nodes
              if n["status"] == "error"}
    assert set(failed) == {f"{ACCT}/OT", f"{ACCT}/OT/LAPTOPS"}
    assert "License limit reached" in \
        failed[f"{ACCT}/OT"]["failed_items"][0]["error"]
    assert "parent site 'OT' not found" in \
        failed[f"{ACCT}/OT/LAPTOPS"]["failed_items"][0]["error"]
    assert _failure_counts(runner._report_nodes) == (2, 2)
