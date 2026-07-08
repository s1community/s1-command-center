"""Tests for the optional OS-keyring token storage in config.py.

Key guarantees:
- With a working keyring, tokens go to the keyring and the file holds only a
  sentinel; load() re-hydrates them.
- With no keyring (or it failing), behaviour falls back to plaintext-in-file —
  never a lockout.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeKeyring:
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def set_password(self, service, user, pw):
        if self.fail:
            raise RuntimeError("backend locked")
        self.store[(service, user)] = pw

    def get_password(self, service, user):
        if self.fail:
            raise RuntimeError("backend locked")
        return self.store.get((service, user))

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


def _cfg(tmp_path, monkeypatch, keyring_obj):
    import config
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE",
                        os.path.join(str(tmp_path), "contexts.json"))
    monkeypatch.setattr(config, "_keyring", lambda: keyring_obj)
    return config


def _raw_file_token(config):
    with open(config.CONFIG_FILE) as f:
        return json.load(f)[0]["api_token"]


def test_keyring_stores_token_and_file_has_sentinel(tmp_path, monkeypatch):
    fk = FakeKeyring()
    config = _cfg(tmp_path, monkeypatch, fk)
    mgr = config.ConfigManager()
    mgr.upsert("Acme", "https://acme.net", "SECRET-TOKEN", role="source")
    # File must NOT contain the real token.
    assert _raw_file_token(config) == config._KEYRING_SENTINEL
    assert fk.store[(config.KEYRING_SERVICE, "https://acme.net")] == "SECRET-TOKEN"
    # A fresh manager re-hydrates the token from the keyring.
    reloaded = config.ConfigManager()
    assert reloaded.get_by_url("https://acme.net").api_token == "SECRET-TOKEN"


def test_no_keyring_falls_back_to_plaintext(tmp_path, monkeypatch):
    config = _cfg(tmp_path, monkeypatch, None)
    mgr = config.ConfigManager()
    mgr.upsert("Acme", "https://acme.net", "PLAINTEXT-TOKEN")
    assert _raw_file_token(config) == "PLAINTEXT-TOKEN"
    assert config.ConfigManager().get_by_url(
        "https://acme.net").api_token == "PLAINTEXT-TOKEN"


def test_keyring_set_failure_falls_back(tmp_path, monkeypatch):
    config = _cfg(tmp_path, monkeypatch, FakeKeyring(fail=True))
    mgr = config.ConfigManager()
    mgr.upsert("Acme", "https://acme.net", "TOK")
    # set_password raised → token kept in file so the connection survives.
    assert _raw_file_token(config) == "TOK"


def test_remove_clears_keyring(tmp_path, monkeypatch):
    fk = FakeKeyring()
    config = _cfg(tmp_path, monkeypatch, fk)
    mgr = config.ConfigManager()
    mgr.upsert("Acme", "https://acme.net", "TOK")
    mgr.remove("https://acme.net")
    assert (config.KEYRING_SERVICE, "https://acme.net") not in fk.store


def test_disable_env_forces_plaintext(tmp_path, monkeypatch):
    # _keyring() returns None when the env flag is set — verify the real fn.
    import config
    monkeypatch.setenv("S1CC_DISABLE_KEYRING", "1")
    assert config._keyring() is None
