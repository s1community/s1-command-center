"""Group ranking must survive a migration, and say so when it doesn't.

Landeshauptstadt München (v2.2.8, 2026-09): every dynamic group came out of
the migration in the wrong order and the restore report showed a clean run.
Two separate defects produced that:

  * ranks were pushed one group at a time from inside the per-group node
    loop, i.e. in backup order. S1 renumbers a site's other groups on every
    rank write, so each PUT returned 200 while the end state was scrambled.
  * the bulk `PUT /groups/ranks` pass sent a partial list of group IDs, got
    a 500 back, and swallowed it into the operation log — the restore report
    never carried a `group-ranks` row at all.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import RestorePage


class FakeAPI:
    """Minimal stand-in for S1API's group surface.

    `reorder_groups` and `update_group` mutate the fake site so the
    verification re-read in _apply_group_ranks sees real state.
    """

    def __init__(self, groups, bulk_error=None, update_error=None):
        self.groups = [dict(g) for g in groups]
        self.bulk_error = bulk_error
        self.update_error = update_error
        self.reorder_calls = []
        self.update_calls = []

    def get_groups(self, params=None):
        return [dict(g) for g in self.groups]

    def _by_id(self, gid):
        return next((g for g in self.groups if str(g["id"]) == str(gid)), None)

    def reorder_groups(self, site_id, group_ids):
        self.reorder_calls.append((site_id, list(group_ids)))
        if self.bulk_error:
            raise self.bulk_error
        for pos, gid in enumerate(group_ids, start=1):
            grp = self._by_id(gid)
            if grp is not None:
                grp["rank"] = pos
        return {}

    def update_group(self, group_id, data):
        self.update_calls.append((str(group_id), dict(data)))
        if self.update_error:
            raise self.update_error
        grp = self._by_id(group_id)
        if grp is not None and "rank" in data:
            grp["rank"] = data["rank"]
        return {}


class Runner:
    """Carries just the state _apply_group_ranks touches, so the ranking
    logic is testable without instantiating a CTk page."""

    _record_site_element = RestorePage._record_site_element
    _apply_group_ranks = RestorePage._apply_group_ranks
    _rerank_groups = RestorePage._rerank_groups

    def __init__(self, report_nodes=None):
        self._operation_log = []
        self._report_nodes = report_nodes if report_nodes is not None else []


def _site_report(path="Acme/Berlin", summary="star: 0"):
    return {"path": path, "type": "site", "status": "done",
            "summary": summary, "elements": {}, "failed_items": []}


DEST_GROUPS = [
    {"id": "1", "name": "Default Group", "type": "static", "rank": None},
    {"id": "2", "name": "Pinned box", "type": "pinned", "rank": None},
    {"id": "3", "name": "Servers", "type": "dynamic", "rank": 1},
    {"id": "4", "name": "Laptops", "type": "dynamic", "rank": 2},
    {"id": "5", "name": "VDI", "type": "dynamic", "rank": 3},
]

# Source order: VDI first, then Servers, then Laptops.
WANTED = {"VDI": 4, "Servers": 11, "Laptops": 26}


# ── the 500: never send a non-dynamic group ─────────────────────────────

def test_only_dynamic_groups_are_sent_to_the_ranks_endpoint():
    api = FakeAPI(DEST_GROUPS)
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    _, sent = api.reorder_calls[0]
    assert sent == ["5", "3", "4"]
    static_and_pinned = {"1", "2"}
    assert not static_and_pinned & set(sent), (
        "/groups/ranks is documented as dynamic-groups-only; a static, "
        "pinned or Default group in the list makes it 500")


def test_source_rank_decides_the_order_not_the_number():
    # Source ranks 4/11/26 are neither contiguous nor 1-based; only their
    # relative order may survive.
    api = FakeAPI(DEST_GROUPS)
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    ranks = {g["name"]: g["rank"] for g in api.groups if g["type"] == "dynamic"}
    assert ranks == {"VDI": 1, "Servers": 2, "Laptops": 3}


def test_the_sites_whole_dynamic_set_is_sent_even_when_unranked():
    # A partial list is the other way to make /groups/ranks 500. Groups the
    # source never ranked keep their relative order at the end.
    dest = DEST_GROUPS + [
        {"id": "6", "name": "DestOnly", "type": "dynamic", "rank": 9}]
    api = FakeAPI(dest)
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    _, sent = api.reorder_calls[0]
    assert sent == ["5", "3", "4", "6"]


def test_a_single_dynamic_group_needs_no_reordering():
    api = FakeAPI([{"id": "3", "name": "Servers", "type": "dynamic",
                    "rank": 1}])
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1",
                                {"Servers": 11})
    assert api.reorder_calls == []
    assert api.update_calls == []


# ── the fallback: bulk endpoint rejected ────────────────────────────────

def test_bulk_rejection_falls_back_to_per_group_rank_writes():
    api = FakeAPI(DEST_GROUPS, bulk_error=RuntimeError(
        "PUT /groups/ranks → 500"))
    runner = Runner([_site_report()])
    runner._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    # Best rank first, so each write only pushes groups not yet placed.
    assert [gid for gid, _ in api.update_calls] == ["5", "3", "4"]
    assert [d["rank"] for _, d in api.update_calls] == [1, 2, 3]
    ranks = {g["name"]: g["rank"] for g in api.groups if g["type"] == "dynamic"}
    assert ranks == {"VDI": 1, "Servers": 2, "Laptops": 3}
    assert runner._report_nodes[0]["elements"]["group-ranks"] == "3 ordered"
    assert runner._report_nodes[0]["status"] == "done"


def test_per_group_writes_carry_the_name_s1_rejects_partial_puts():
    api = FakeAPI(DEST_GROUPS, bulk_error=RuntimeError("boom"))
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    assert all("name" in payload for _, payload in api.update_calls)


def test_bulk_success_skips_the_per_group_fallback():
    api = FakeAPI(DEST_GROUPS)
    Runner()._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    assert api.update_calls == []


# ── the silence: a failed ranking must reach the report ─────────────────

def test_total_failure_is_recorded_on_the_site_report_row():
    api = FakeAPI(DEST_GROUPS,
                  bulk_error=RuntimeError("PUT /groups/ranks → 500"),
                  update_error=RuntimeError("403 Insufficient permissions"))
    report = _site_report()
    runner = Runner([report])
    runner._apply_group_ranks(api, "Acme/Berlin", "site-1", WANTED)
    assert report["elements"]["group-ranks"].startswith("ERR:")
    assert "3/3" in report["elements"]["group-ranks"]
    assert report["status"] == "error"
    assert "group-ranks" in report["summary"]


def test_success_is_recorded_on_the_site_report_row():
    report = _site_report()
    runner = Runner([report])
    runner._apply_group_ranks(FakeAPI(DEST_GROUPS), "Acme/Berlin", "site-1",
                              WANTED)
    assert report["elements"]["group-ranks"] == "3 ordered"
    assert report["status"] == "done"


def test_report_row_matches_the_site_even_with_a_trailing_slash():
    report = _site_report(path="Acme/Berlin/")
    runner = Runner([report])
    runner._apply_group_ranks(FakeAPI(DEST_GROUPS), "Acme/Berlin", "site-1",
                              WANTED)
    assert "group-ranks" in report["elements"]


def test_ranking_survives_a_site_with_no_report_row():
    runner = Runner([])
    runner._apply_group_ranks(FakeAPI(DEST_GROUPS), "Acme/Berlin", "site-1",
                              WANTED)
    assert any("ordered" in line for line in runner._operation_log)


# ── walking the backup ──────────────────────────────────────────────────

class TreeAPI(FakeAPI):
    def get_accounts(self):
        return [{"id": "a1", "name": "Acme"}]

    def get_sites(self, params=None):
        return [{"id": "site-1", "name": "Berlin"}]


def _group_node(name, rank, gtype="dynamic"):
    return {"type": "group", "path": f"Acme/Berlin/{name}",
            "group": {"name": name, "rank": rank, "type": gtype}}


def test_rerank_reads_ranks_from_the_backup_tree():
    backup = [
        {"type": "account", "path": "Acme/"},
        {"type": "site", "path": "Acme/Berlin"},
        _group_node("VDI", 4),
        _group_node("Servers", 11),
        _group_node("Laptops", 26),
        # static / pinned groups have no rank and must not reach the endpoint
        _group_node("Default Group", None, "static"),
        _group_node("Pinned box", None, "pinned"),
    ]
    api = TreeAPI(DEST_GROUPS)
    Runner()._rerank_groups(api, backup)
    assert api.reorder_calls[0][1] == ["5", "3", "4"]


def test_rerank_is_a_noop_without_ranked_groups():
    api = TreeAPI(DEST_GROUPS)
    Runner()._rerank_groups(api, [{"type": "site", "path": "Acme/Berlin"}])
    assert api.reorder_calls == []


# ── source guard ────────────────────────────────────────────────────────

def test_the_node_loop_no_longer_writes_rank_group_by_group():
    src = inspect.getsource(RestorePage._resolve_dest_id)
    assert 'for k in ("description",):' in src, (
        "the per-group drift sync must not push `rank`: applying ranks in "
        "backup order makes S1 renumber the neighbours on every call and "
        "scrambles the site's final order")
