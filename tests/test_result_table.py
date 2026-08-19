"""ResultTable row placement.

Every operations page renders through this table, and a batch load used to
put its first row on grid row 0 — on top of the column headers, which is
what made the Tags audit print "own" over "owned". These need a display, so
they skip rather than fail on a headless machine.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ctk = pytest.importorskip("customtkinter")


@pytest.fixture
def root():
    try:
        win = ctk.CTk()
    except Exception as exc:  # no display available
        pytest.skip(f"Tk unavailable: {exc}")
    win.withdraw()
    yield win
    win.destroy()


@pytest.fixture
def table(root):
    from pages_extra import ResultTable
    return ResultTable(root, ["name", "id"])


def _rows_at(table, grid_row):
    return [w.cget("text") for w in table.winfo_children()
            if w.grid_info().get("row") == grid_row]


def test_headers_stay_on_the_first_grid_row(table):
    table.load([{"name": "SiteTag", "id": "t1"}])
    assert _rows_at(table, 0) == ["name", "id"]


def test_first_loaded_row_does_not_cover_the_header(table):
    table.load([{"name": "SiteTag", "id": "t1"}])
    assert _rows_at(table, 1) == ["SiteTag", "t1"]


def test_rows_keep_one_grid_row_each(table):
    table.load([{"name": f"tag{i}", "id": str(i)} for i in range(5)])
    for i in range(5):
        assert _rows_at(table, i + 1) == [f"tag{i}", str(i)]


def test_a_second_load_starts_over_without_shifting(table):
    table.load([{"name": "first", "id": "1"}])
    table.load([{"name": "second", "id": "2"}])
    assert _rows_at(table, 0) == ["name", "id"]
    assert _rows_at(table, 1) == ["second", "2"]
    assert table._rows == [{"name": "second", "id": "2"}]


def test_batching_does_not_reuse_a_grid_row(table):
    # Batch boundaries are where an off-by-one would reappear.
    table.load([{"name": f"tag{i}", "id": str(i)} for i in range(4)],
               batch_size=2)
    while table._pending_items:
        table.update()
    occupied = [w.grid_info()["row"] for w in table.winfo_children()]
    assert sorted(occupied) == sorted([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
