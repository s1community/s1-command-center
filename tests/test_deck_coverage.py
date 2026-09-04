"""Guard test: the customer-facing scope deck must match what the tool does.

The "what can / cannot be migrated" deck is what customers plan their cutover
around, so a stale slide is a support ticket. Before this test the shipped deck
advertised Service Users and Gateways as migrated (they are captured for
reporting and deliberately never written), listed "Policy override" as NOT
migrated while also listing "Config Overrides" as migrated (same element), and
omitted Unified Exclusions, Webhooks and Scheduled Reports entirely.

``scripts/build_migration_scope_deck.py`` therefore declares, per element,
which side of the deck it belongs on. This test ties that declaration to
``pages.BACKUP_ELEMENTS`` and to ``tests/test_restore_coverage._NOT_RESTORED``
so the deck can't drift from the code again.
"""
import importlib.util
import inspect
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pages import BACKUP_ELEMENTS, RestorePage  # noqa: E402
from test_restore_coverage import _NOT_RESTORED  # noqa: E402


def _load_deck():
    path = os.path.join(ROOT, "scripts", "build_migration_scope_deck.py")
    spec = importlib.util.spec_from_file_location("_deck_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deck = _load_deck()


def test_every_backup_element_appears_on_a_slide():
    declared = set(deck.ELEMENT_SLIDES)
    known = set(BACKUP_ELEMENTS)
    assert declared == known, (
        "the scope deck and BACKUP_ELEMENTS disagree — "
        f"missing from the deck: {sorted(known - declared)}; "
        f"no longer a backup element: {sorted(declared - known)}")


def test_deck_side_matches_what_restore_actually_writes():
    silent = _NOT_RESTORED | deck.INVENTORY_ONLY
    for element, (group, _phrase) in deck.ELEMENT_SLIDES.items():
        expected = "not_migrated" if element in silent else "migrated"
        assert group == expected, (
            f"'{element}' is on the deck's '{group}' slide but the restore "
            f"loop treats it as '{expected}'")


@pytest.mark.parametrize("element", sorted(deck.INVENTORY_ONLY))
def test_inventory_only_branches_never_write_to_the_destination(element):
    # If someone later teaches the restore loop to actually create these, the
    # deck must move them to the "can be migrated" side.
    src = inspect.getsource(RestorePage._run_restore)
    start = src.index(f'"{element}" in elements')
    end = src.index("results.append((", start)
    branch = src[start:end]
    assert "manually" in branch, (
        f"the '{element}' restore branch no longer tells the operator to "
        f"re-create it manually")
    assert not re.search(r"\bapi\.", branch), (
        f"the '{element}' restore branch now calls the API — it writes to the "
        f"destination, so move it off the deck's 'will not be migrated' slide "
        f"and out of INVENTORY_ONLY")


@pytest.mark.parametrize("element", sorted(deck.ELEMENT_SLIDES))
def test_declared_phrase_is_really_on_that_slide(element):
    group, phrase = deck.ELEMENT_SLIDES[element]
    cards = (deck.MIGRATED_CARDS if group == "migrated"
             else deck.NOT_MIGRATED_CARDS)
    text = "\n".join(deck.bullets(cards))
    assert phrase in text, (
        f"'{element}' claims the '{group}' slides say {phrase!r}, but no "
        f"bullet there contains it — the deck copy was edited without "
        f"updating ELEMENT_SLIDES")


def test_migrated_and_not_migrated_slides_do_not_contradict():
    # The old deck listed "Policy override" as not migrated while listing
    # "Config Overrides" as migrated. Nothing on the not-migrated slides may
    # repeat a phrase the migrated slides claim.
    not_text = "\n".join(deck.bullets(deck.NOT_MIGRATED_CARDS))
    for element, (group, phrase) in deck.ELEMENT_SLIDES.items():
        if group != "migrated":
            continue
        assert phrase not in not_text, (
            f"'{element}' is advertised as migrated but {phrase!r} also "
            f"appears on the 'will not be migrated' slide")


def test_caveats_cover_the_known_partial_migrations():
    text = "\n".join(deck.bullets(deck.CAVEAT_CARDS)).lower()
    # SMTP password is write-only; the restore reports it as a skip.
    assert "smtp" in text and "password" in text
    # SSO SAML material is bound to the source tenant URL.
    assert "sso" in text
