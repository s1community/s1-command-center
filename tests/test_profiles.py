"""Unit tests for the migration ProfileManager (config.py).

Profiles persist a reusable scope + element selection, so round-tripping and
the no-secrets guarantee are the important behaviours to lock down.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_manager(tmp_path, monkeypatch):
    """Reload config with CONFIG_DIR pointed at a temp dir so tests don't
    touch the real ~/.s1-command-center."""
    import config
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PROFILES_FILE",
                        os.path.join(str(tmp_path), "migration_profiles.json"))
    return config


def test_upsert_and_get(tmp_path, monkeypatch):
    config = _fresh_manager(tmp_path, monkeypatch)
    mgr = config.ProfileManager()
    mgr.upsert("Acme", elements=["policy", "exclusions"],
               levels={"global": False, "accounts": True},
               filters={"account": "Acme", "site": "", "group": ""},
               created_at="2026-06-29T00:00:00+00:00")
    p = mgr.get("Acme")
    assert p is not None
    assert p.elements == ["policy", "exclusions"]
    assert p.levels["accounts"] is True
    assert p.filters["account"] == "Acme"


def test_upsert_overwrites_same_name_and_keeps_created_at(tmp_path, monkeypatch):
    config = _fresh_manager(tmp_path, monkeypatch)
    mgr = config.ProfileManager()
    mgr.upsert("Acme", elements=["policy"], created_at="2026-01-01T00:00:00+00:00")
    mgr.upsert("acme", elements=["policy", "blocklist"])  # case-insensitive
    assert len(mgr.profiles) == 1
    p = mgr.get("Acme")
    assert p.elements == ["policy", "blocklist"]
    assert p.created_at == "2026-01-01T00:00:00+00:00"  # preserved on overwrite


def test_persistence_round_trip(tmp_path, monkeypatch):
    config = _fresh_manager(tmp_path, monkeypatch)
    config.ProfileManager().upsert(
        "Acme", elements=["policy"], filters={"site": "HQ"})
    # New manager instance reads from disk.
    reloaded = config.ProfileManager()
    p = reloaded.get("Acme")
    assert p is not None
    assert p.filters["site"] == "HQ"


def test_profile_holds_no_secrets(tmp_path, monkeypatch):
    """Profiles must never carry API tokens — those live in contexts.json."""
    config = _fresh_manager(tmp_path, monkeypatch)
    mgr = config.ProfileManager()
    mgr.upsert("Acme", elements=["policy"])
    from dataclasses import asdict
    blob = asdict(mgr.get("Acme"))
    assert "api_token" not in blob
    assert "token" not in " ".join(blob.keys()).lower()


def test_remove(tmp_path, monkeypatch):
    config = _fresh_manager(tmp_path, monkeypatch)
    mgr = config.ProfileManager()
    mgr.upsert("Acme", elements=["policy"])
    mgr.remove("acme")  # case-insensitive
    assert mgr.get("Acme") is None
    assert mgr.names() == []
