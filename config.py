"""
Configuration / Context Manager — stores source & destination console connections.
"""
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".s1-command-center")
CONFIG_FILE = os.path.join(CONFIG_DIR, "contexts.json")


@dataclass
class Context:
    name: str
    url: str
    api_token: str
    role: str = ""  # "source" or "destination"

    @property
    def display_url(self) -> str:
        return self.url.replace("https://", "").replace("http://", "").rstrip("/")


class ConfigManager:
    def __init__(self):
        self.contexts: list[Context] = []
        os.makedirs(CONFIG_DIR, exist_ok=True)
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

    def upsert(self, name: str, url: str, api_token: str, role: str = "") -> Context:
        if not url.startswith("http"):
            url = f"https://{url}.sentinelone.net"
        self.contexts = [c for c in self.contexts if c.name != name]
        ctx = Context(name=name, url=url, api_token=api_token, role=role)
        self.contexts.append(ctx)
        self.save()
        return ctx

    def remove(self, name: str):
        self.contexts = [c for c in self.contexts if c.name != name]
        self.save()

    def get(self, name: str) -> Optional[Context]:
        return next((c for c in self.contexts if c.name == name), None)

    def get_by_role(self, role: str) -> Optional[Context]:
        return next((c for c in self.contexts if c.role == role), None)

    def set_role(self, name: str, role: str):
        for c in self.contexts:
            if c.role == role:
                c.role = ""
            if c.name == name:
                c.role = role
        self.save()

    def names(self) -> list[str]:
        return [c.name for c in self.contexts]
