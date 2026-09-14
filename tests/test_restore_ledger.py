"""End-to-end proof that a restore names what it could not migrate.

The source guards in test_gap_report.py prove every branch *calls* the
ledger. This drives the REAL RestorePage._run_restore against a fake
console so the whole chain is exercised: 45 exclusions in, 43 created, and
the report has to name the exact two that failed.

RestorePage is a CTk widget, so the harness below mirrors the technique in
test_group_ranking.py: bind the real method onto a plain object that
carries only the state the method touches.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_utils import build_gap_report
from pages import RestorePage
from s1_api import S1APIError


# ── Harness ────────────────────────────────────────────────────────────

class _Widget:
    """Absorbs every progress-table / button call the restore makes."""

    def __getattr__(self, _name):
        return lambda *a, **kw: None


class Runner:
    _run_restore = RestorePage._run_restore
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

    # Run UI callbacks inline — there is no event loop in a unit test.
    def after(self, _delay, fn=None):
        if fn is not None:
            fn()

    def _resolve_dest_id(self, api, node, log, progress=None):
        return "dest-1"

    def _rerank_groups(self, api, backup):
        return None


BAD = {"C:\\bad\\one.exe", "C:\\bad\\two.exe"}


class FakeAPI:
    """Rejects two exclusions, reports one blocklist hash as a duplicate."""

    base_url = "https://dest.sentinelone.net"

    def __init__(self):
        self.created = []

    def create_exclusion(self, scope, payload):
        if payload.get("value") in BAD:
            raise S1APIError("POST /exclusions → 400", status_code=400,
                             detail="Validation Error :: data: value: "
                                    "invalid path")
        self.created.append(payload["value"])
        return {"data": {"id": "x"}}

    def create_restriction(self, scope, payload):
        if payload.get("value") == "dupe-hash":
            raise S1APIError("POST /restrictions → 409", status_code=409,
                             detail="Item already exists")
        return {"data": {"id": "b"}}

    def __getattr__(self, name):
        # Any other endpoint the restore reaches for is a no-op success.
        def _noop(*a, **kw):
            return {}
        return _noop


def _backup():
    values = [f"C:\\app{i}.exe" for i in range(43)] + sorted(BAD)
    return [{
        "type": "site",
        "path": "Acme/Berlin",
        "site": {"name": "Berlin"},
        "data": {
            "exclusions": {"path": [{"value": v, "osType": "windows"}
                                    for v in values]},
            "restrictions": [{"value": "dupe-hash", "type": "black_hash"},
                             {"value": "new-hash", "type": "black_hash"}],
            "locations": [],
        },
    }]


def _run(elements=("exclusions", "blocklist", "locations")):
    runner = Runner()
    api = FakeAPI()
    runner._run_restore(api, _backup(), list(elements),
                        levels={"global": False, "accounts": False,
                                "sites": True, "groups": False})
    return runner, api


# ── Tests ──────────────────────────────────────────────────────────────

def test_restore_records_one_ledger_row_per_exclusion():
    runner, _api = _run()
    excl = [r for r in runner._item_ledger if r["element"] == "excl"]
    assert len(excl) == 45


def test_report_names_the_two_exclusions_that_did_not_migrate():
    runner, api = _run()
    assert len(api.created) == 43

    report = build_gap_report(runner._item_ledger)
    tab = {e["key"]: e for e in report["elements"]}["excl"]
    assert (tab["total"], tab["restored"], tab["missing"]) == (45, 43, 2)
    assert {r["item"] for r in tab["rows"]
            if r["status"] == "failed"} == BAD
    # The reason travels with the item, so the operator can act on it.
    assert all("invalid path" in r["reason"]
               for r in tab["rows"] if r["status"] == "failed")


def test_ledger_rows_carry_the_scope_and_the_exclusion_type():
    runner, _api = _run()
    row = next(r for r in runner._item_ledger if r["element"] == "excl")
    assert row["node"] == "Acme/Berlin"
    assert row["scope"] == "site"
    assert row["kind"] == "path"


def test_duplicate_on_destination_counts_as_restored_not_missing():
    runner, _api = _run()
    tab = {e["key"]: e for e in
           build_gap_report(runner._item_ledger)["elements"]}["blocklist"]
    assert tab["missing"] == 0
    assert tab["counts"]["exists"] == 1 and tab["counts"]["created"] == 1


def test_element_with_nothing_in_the_backup_still_gets_a_row():
    """A selected element that wrote nothing must never vanish silently —
    that is how endpoint tags and auto-upgrade policies went missing."""
    runner, _api = _run()
    locs = [r for r in runner._item_ledger if r["element"] == "locations"]
    assert locs and locs[0]["status"] in ("empty", "not attempted")


def test_unselected_elements_produce_no_rows():
    runner, _api = _run(elements=("exclusions",))
    assert {r["element"] for r in runner._item_ledger} == {"excl"}


def test_cancelling_names_every_item_it_never_reached():
    """A stopped run must still say which items were left behind."""
    runner = Runner()
    api = FakeAPI()
    real_create = api.create_exclusion

    def cancel_after_five(scope, payload):
        if len(api.created) >= 5:
            runner._cancelled = True
        return real_create(scope, payload)

    api.create_exclusion = cancel_after_five
    runner._run_restore(api, _backup(), ["exclusions"],
                        levels={"global": False, "accounts": False,
                                "sites": True, "groups": False})
    excl = [r for r in runner._item_ledger if r["element"] == "excl"]
    assert len(excl) == 45, "cancelled items must still be listed by name"
    skipped = [r for r in excl if r["status"] == "skipped"]
    assert len(skipped) == 45 - len(api.created)
    assert all("cancelled" in r["reason"] for r in skipped)
