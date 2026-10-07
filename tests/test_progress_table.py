"""The progress view groups a run by site and counts each site on its own."""
import pytest

import pages

ACCT = "FAO"
FAO = (("FAO-DEFAULT", ["Default Group"]),
       ("FAO-TEST", ["Default Group", "Servers", "Laptops"]))


@pytest.fixture
def table():
    import customtkinter as ctk
    try:
        root = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    widget = pages.ProgressTable(root)
    widget.pack(fill="both", expand=True)
    yield widget
    root.destroy()


def _add(table, sites=FAO, account=ACCT):
    num = 1
    table.add_node(f"a:{account}", f"{account}/", "account", num=num)
    for site, groups in sites:
        num += 1
        table.add_node(f"s:{account}/{site}", f"{account}/{site}", "site",
                       num=num)
        for group in groups:
            num += 1
            table.add_node(f"g:{account}/{site}/{group}",
                           f"{account}/{site}/{group}", "group", num=num)
    table.update_idletasks()


def _many(count=5, groups=4):
    return tuple((f"SITE-{s}", [f"Group {g}" for g in range(1, groups + 1)])
                 for s in range(1, count + 1))


def _card(table, nid):
    return table._sections[table._rows[nid]["key"]]


def _text(widget):
    return widget.cget("text")


def _shown(widget):
    return bool(widget.winfo_manager())


def _row(table, nid, part):
    items = table._rows[nid]["items"]
    return None if items is None else table._view.itemcget(items[part], "text")


def _head(table, key, part):
    items = table._sections[key]["items"]
    return None if items is None else table._view.itemcget(items[part], "text")


def _rows_drawn(table, key):
    return [table._rows[n]["items"] is not None
            for n in table._sections[key]["rows"]]


def test_groups_are_numbered_within_their_own_site(table):
    _add(table)
    marks = [_row(table, f"g:FAO/FAO-TEST/{g}", "mark")
             for g in ("Default Group", "Servers", "Laptops")]
    assert marks == ["1", "2", "3"]
    assert _row(table, "g:FAO/FAO-DEFAULT/Default Group", "mark") == "1"
    assert _row(table, "s:FAO/FAO-TEST", "name") == "Site settings"


def test_each_site_gets_its_own_numbered_card(table):
    _add(table)
    assert [_head(table, k, "title") for k in table._order] == \
        ["FAO", "FAO-DEFAULT", "FAO-TEST"]
    assert [_head(table, k, "glyph") for k in table._order] == \
        ["A", "1", "2"]


def test_the_same_site_name_in_two_accounts_is_two_cards(table):
    _add(table, sites=(("HQ", ["Servers"]),), account="ACME")
    _add(table, sites=(("HQ", ["Servers"]),), account="FAO")
    assert _card(table, "g:ACME/HQ/Servers") is not \
        _card(table, "g:FAO/HQ/Servers")
    assert _row(table, "g:FAO/HQ/Servers", "mark") == "1"


def test_the_backup_position_stays_in_the_tooltip(table):
    _add(table)
    assert "node 4 in the backup" in table._rows["s:FAO/FAO-TEST"]["tip"]


def test_a_card_counts_only_its_own_rows(table):
    _add(table)
    table.set_done("s:FAO/FAO-TEST", "policy ✓")
    table.set_done("g:FAO/FAO-TEST/Default Group", "policy ✓")
    table.set_error("g:FAO/FAO-TEST/Servers", "400 Bad Request")
    assert _head(table, "s:FAO/FAO-TEST", "count") == "2/4"
    assert _head(table, "s:FAO/FAO-TEST", "issues") == "1 failed"
    assert _head(table, "s:FAO/FAO-DEFAULT", "count") == "0/2"


def test_the_summary_tallies_the_whole_run(table):
    _add(table)
    table.set_done("a:FAO", "")
    table.set_error("s:FAO/FAO-TEST", "boom")
    table.set_skipped("s:FAO/FAO-DEFAULT", "cancelled")
    assert _text(table._scope_lbl) == "1 account · 2 sites · 4 groups"
    tallies = {k: _text(lbl) for k, (lbl, _mark) in table._tally.items()
               if _shown(lbl)}
    assert tallies == {"done": "✓ 1 done", "error": "✗ 1 failed",
                       "skipped": "⏭ 1 skipped", "pending": "◌ 4 waiting"}


def test_the_badge_follows_the_site(table):
    _add(table)
    card = _card(table, "s:FAO/FAO-DEFAULT")
    table.set_running("s:FAO/FAO-DEFAULT")
    assert table._view.itemcget(card["items"]["badge"], "fill") == \
        pages.theme.tkcolor(pages.BRAND)
    table.set_done("s:FAO/FAO-DEFAULT", "ok")
    table.set_done("g:FAO/FAO-DEFAULT/Default Group", "ok")
    assert _head(table, "s:FAO/FAO-DEFAULT", "glyph") == "✓"
    for nid in ("s:FAO/FAO-TEST", "g:FAO/FAO-TEST/Default Group",
                "g:FAO/FAO-TEST/Servers"):
        table.set_done(nid, "ok")
    table.set_error("g:FAO/FAO-TEST/Laptops", "boom")
    assert _head(table, "s:FAO/FAO-TEST", "glyph") == "!"


def test_a_small_run_keeps_every_site_open(table):
    _add(table)
    for nid in table._sections["s:FAO/FAO-DEFAULT"]["rows"]:
        table.set_done(nid, "ok")
    assert all(_rows_drawn(table, "s:FAO/FAO-DEFAULT"))


def test_a_big_run_folds_finished_sites_and_opens_the_live_one(table):
    _add(table, sites=_many())
    first, second = "s:FAO/SITE-1", "s:FAO/SITE-2"
    assert not any(_rows_drawn(table, first))
    table.set_running(f"g:{first[2:]}/Group 1")
    assert all(_rows_drawn(table, first))
    for nid in table._sections[first]["rows"]:
        table.set_done(nid, "ok")
    assert not any(_rows_drawn(table, first))
    table.set_running(f"g:{second[2:]}/Group 1")
    table.set_error(f"g:{second[2:]}/Group 1", "boom")
    for nid in table._sections[second]["rows"][2:]:
        table.set_done(nid, "ok")
    table.set_done(second, "ok")
    assert all(_rows_drawn(table, second))


def test_folded_sites_draw_their_rows_only_when_opened(table):
    _add(table, sites=_many())
    card = table._sections["s:FAO/SITE-3"]
    assert not any(_rows_drawn(table, "s:FAO/SITE-3"))
    table._toggle_section(card)
    assert all(_rows_drawn(table, "s:FAO/SITE-3"))


def test_the_list_is_drawn_on_the_canvas_not_built_from_widgets(table):
    _add(table, sites=_many())
    table._toggle_fold_all()
    assert all(_rows_drawn(table, "s:FAO/SITE-5"))
    assert table._view.winfo_children() == []


def test_the_frame_keeps_its_own_background_canvas(table):
    import customtkinter as ctk
    assert isinstance(table._canvas, ctk.CTkCanvas)
    assert table._view is not table._canvas


def test_long_text_is_shortened_to_one_line(table):
    long_name = "Workstations " * 30
    _add(table, sites=(("FAO-TEST", [long_name.strip()]),))
    nid = f"g:FAO/FAO-TEST/{long_name.strip()}"
    table.set_error(nid, "first line\nsecond line " + "x" * 400)
    name, detail = _row(table, nid, "name"), _row(table, nid, "detail")
    assert name.endswith("…") and len(name) < len(long_name)
    assert "\n" not in detail and detail.endswith("…")


def test_a_site_the_user_folded_stays_folded(table):
    _add(table)
    card = table._sections["s:FAO/FAO-TEST"]
    table._toggle_section(card)
    table.set_running("g:FAO/FAO-TEST/Servers")
    assert not any(_rows_drawn(table, "s:FAO/FAO-TEST"))


def test_failed_only_hides_clean_sites_and_rows(table):
    _add(table)
    table.set_done("s:FAO/FAO-TEST", "ok")
    table.set_error("g:FAO/FAO-TEST/Servers", "boom")
    assert _shown(table._failed_btn)
    table._toggle_only_failed()
    assert table._sections["s:FAO/FAO-DEFAULT"]["items"] is None
    assert table._rows["s:FAO/FAO-TEST"]["items"] is None
    assert table._rows["g:FAO/FAO-TEST/Servers"]["items"] is not None
    table._toggle_only_failed()
    assert table._sections["s:FAO/FAO-DEFAULT"]["items"] is not None
    assert table._rows["s:FAO/FAO-TEST"]["items"] is not None


def test_the_status_line_counts_per_site(table):
    _add(table)
    assert table.position_text("g:FAO/FAO-TEST/Servers") == \
        "site 2 of 2 · FAO-TEST — group 2 of 3: Servers"
    assert table.position_text("s:FAO/FAO-DEFAULT") == \
        "site 1 of 2 · FAO-DEFAULT — site settings"
    assert table.position_text("a:FAO") == "account FAO — account settings"


def test_scrollbar_redraws_are_batched_not_per_layout_change(table,
                                                             monkeypatch):
    calls = []
    monkeypatch.setattr(table._vscroll, "set", lambda *a: calls.append(a))
    command = table._view["yscrollcommand"]
    for end in ("0.2", "0.4", "0.6"):
        table.tk.call(command, "0.0", end)
    assert calls == []
    table._apply_scrollbar()
    assert calls == [("0.0", "0.6")]


def test_clear_returns_to_the_empty_state(table):
    _add(table)
    assert not _shown(table._empty)
    table.clear()
    assert _shown(table._empty) and not _shown(table._view)
    _add(table, sites=(("FAO-TEST", ["Servers"]),))
    assert _head(table, "s:FAO/FAO-TEST", "glyph") == "1"
