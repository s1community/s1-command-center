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


_SITE_ONLY = {"global": False, "accounts": False,
              "sites": True, "groups": False}


def _run(elements=("exclusions", "blocklist", "locations")):
    runner = Runner()
    api = FakeAPI()
    runner._run_restore(api, _backup(), list(elements), levels=_SITE_ONLY)
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


# ── Exclusion names — DGS S.p.A., case #01714638 ───────────────────
# "The number of exclusions in the target console is correct, however for
# some of the migrated ones we do not see the Exclusion Name." The name
# lives ONLY on the unified resource; the legacy /exclusions create has no
# field for it. Both elements ship selected by default and every backup
# holds the same exclusions under both, so whichever runs first decides
# whether the name survives.

EXCL_VALUE = "C:\\tools\\agent.exe"


class NameAPI(FakeAPI):
    """FakeAPI that also records what the unified endpoint was sent.

    `on_destination` is what GET /unified-exclusions returns, i.e. what a
    previous migration already left on the target console.
    """

    def __init__(self, on_destination=()):
        super().__init__()
        self.unified = []
        self.updated = []
        self.on_destination = list(on_destination)

    def create_unified_exclusion(self, _filter, payload):
        if any(d.get("value") == payload.get("value")
               for d in self.on_destination):
            raise S1APIError("POST /unified-exclusions → 400",
                             status_code=400,
                             detail="Exclusion already exists")
        self.unified.append(payload)
        return {"data": {"id": "u"}}

    def get_unified_exclusions(self, _scope):
        return list(self.on_destination)

    def update_unified_exclusion(self, _filter, payload):
        self.updated.append(payload)
        return {"data": {"id": payload.get("id")}}


def _both_views_backup(with_unified=True):
    """One exclusion as a real backup holds it: in BOTH element lists."""
    legacy = {"value": EXCL_VALUE, "osType": "windows", "type": "path"}
    data = {"exclusions": {"path": [legacy]}}
    if with_unified:
        data["unified_exclusions"] = [
            dict(legacy, exclusionName="Vendor agent",
                 modeType="suppression", threatType="EDR")]
    return [{"type": "site", "path": "Acme/Berlin",
             "site": {"name": "Berlin"}, "data": data}]


def _run_both(with_unified=True, api=None):
    runner = Runner()
    api = api or NameAPI()
    runner._run_restore(api, _both_views_backup(with_unified),
                        ["exclusions", "unified_exclusions"],
                        levels=_SITE_ONLY)
    return runner, api


def test_the_exclusion_name_reaches_the_destination():
    _runner, api = _run_both()
    assert [p.get("exclusionName") for p in api.unified] == ["Vendor agent"]


def test_the_same_exclusion_is_not_created_through_both_apis():
    # A legacy create carries no name, so a second write of an exclusion
    # the unified pass already landed can only produce the nameless copy
    # the customer reported.
    _runner, api = _run_both()
    assert api.created == [], \
        "legacy /exclusions must not re-create a unified exclusion"


def test_the_skipped_legacy_items_are_explained_not_counted_as_missing():
    runner, _api = _run_both()
    rows = [r for r in runner._item_ledger if r["element"] == "excl"]
    assert len(rows) == 1 and rows[0]["status"] == "inherited"
    assert "Unified Exclusions" in rows[0]["reason"]
    tab = {e["key"]: e for e in
           build_gap_report(runner._item_ledger)["elements"]}["excl"]
    assert tab["missing"] == 0


def test_legacy_still_runs_when_the_backup_has_no_unified_exclusions():
    _runner, api = _run_both(with_unified=False)
    assert api.created == [EXCL_VALUE]


# An already-migrated tenant is the harder half of the same bug: the
# nameless copies are on the destination, so a re-run's create is just
# answered "already exists" and nothing changes. PUT /unified-exclusions
# is the only call that can name them.

def _already_migrated(name_on_dest=None):
    dest = {"id": "dest-7", "value": EXCL_VALUE, "osType": "windows",
            "type": "path", "modeType": "suppression",
            "threatType": "EDR", "reason": None}
    if name_on_dest is not None:
        dest["exclusionName"] = name_on_dest
    return NameAPI(on_destination=[dest])


def test_a_nameless_exclusion_already_on_the_destination_gets_its_name():
    _runner, api = _run_both(api=_already_migrated())
    assert len(api.updated) == 1
    sent = api.updated[0]
    assert sent["exclusionName"] == "Vendor agent"
    assert sent["id"] == "dest-7"
    # The edit schema demands these even when only the name changes, and
    # the console hands `reason` back as null.
    for field in ("modeType", "osType", "reason", "threatType", "type"):
        assert sent.get(field), f"{field} must be sent on an update"


def test_a_name_set_on_the_destination_is_never_overwritten():
    _runner, api = _run_both(api=_already_migrated("Named by the customer"))
    assert api.updated == []


def test_the_applied_name_is_reported_against_the_item():
    runner, _api = _run_both(api=_already_migrated())
    row = next(r for r in runner._item_ledger
               if r["element"] == "unified-excl")
    assert row["status"] == "exists"
    assert "name" in row["reason"]


def test_a_refused_rename_does_not_fail_the_item():
    api = _already_migrated()

    def _refuse(_filter, _payload):
        raise S1APIError("PUT /unified-exclusions → 403", status_code=403,
                         detail="Exclusions.edit permission required")

    api.update_unified_exclusion = _refuse
    runner, _api = _run_both(api=api)
    row = next(r for r in runner._item_ledger
               if r["element"] == "unified-excl")
    assert row["status"] == "exists"
    assert any("rename was refused" in line
               for line in runner._operation_log)


def test_legacy_still_runs_when_the_unified_create_fails():
    # Older destinations have no unified-exclusions resource. Skipping the
    # legacy write on their behalf would migrate nothing at all.
    api = NameAPI()

    def _unsupported(_filter, _payload):
        raise S1APIError("POST /unified-exclusions → 404", status_code=404,
                         detail="Not found")

    api.create_unified_exclusion = _unsupported
    _runner, api = _run_both(api=api)
    assert api.created == [EXCL_VALUE]


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
