"""
Configuration / Context Manager — stores source & destination console connections.
"""
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

CONFIG_DIR   = os.path.join(os.path.expanduser("~"), ".s1-command-center")
CONFIG_FILE  = os.path.join(CONFIG_DIR, "contexts.json")


@dataclass
class Context:
    name: str
    url: str
    api_token: str
    role: str = ""  # "source" or "destination"
    ignore_ssl_errors: bool = False

    @property
    def display_url(self) -> str:
        return self.url.replace("https://", "").replace("http://", "").rstrip("/")


class ConfigManager:
    def __init__(self):
        self.contexts: list[Context] = []
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            os.chmod(CONFIG_DIR, 0o700)  # owner-only — the dir holds secrets
        except OSError:
            pass
        self.load()

    def load(self):
        if not os.path.exists(CONFIG_FILE):
            self.contexts = []
            return
        try:
            with open(CONFIG_FILE, "r") as f:
                self.contexts = [Context(**c) for c in json.load(f)]
        except Exception:
            self.contexts = []

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump([asdict(c) for c in self.contexts], f, indent=2)
        # Tokens are stored in plaintext here — lock the file down to the
        # owner so other local users can't read the API credentials.
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            pass  # best-effort (e.g. Windows / unusual filesystems)

    def upsert(self, name: str, url: str, api_token: str, role: str = "",
               ignore_ssl_errors: bool = False) -> Context:
        if not url.startswith("http"):
            url = f"https://{url}.sentinelone.net"
        # A console's identity is its URL, not its friendly name — ticket
        # data often gives the same account name to both source and
        # destination consoles, so deduping by name would wipe one of them.
        self.contexts = [c for c in self.contexts if c.url != url]
        ctx = Context(name=name, url=url, api_token=api_token, role=role,
                      ignore_ssl_errors=bool(ignore_ssl_errors))
        self.contexts.append(ctx)
        self.save()
        return ctx

    def remove(self, url_or_name: str):
        """Remove by URL first; fall back to name for legacy callers."""
        before = len(self.contexts)
        self.contexts = [c for c in self.contexts if c.url != url_or_name]
        if len(self.contexts) == before:
            self.contexts = [c for c in self.contexts if c.name != url_or_name]
        self.save()

    def get(self, name: str) -> Optional[Context]:
        return next((c for c in self.contexts if c.name == name), None)

    def get_by_url(self, url: str) -> Optional[Context]:
        return next((c for c in self.contexts if c.url == url), None)

    def get_by_role(self, role: str) -> Optional[Context]:
        return next((c for c in self.contexts if c.role == role), None)

    def set_role(self, identifier: str, role: str):
        """Promote the context with this URL (or name, for legacy) to the
        given role, demoting any other context that currently holds it."""
        target = self.get_by_url(identifier) or self.get(identifier)
        if not target:
            return
        for c in self.contexts:
            if c is target:
                c.role = role
            elif c.role == role:
                c.role = ""
        self.save()

    def names(self) -> list[str]:
        return [c.name for c in self.contexts]
