"""
Configuration / Context Manager — stores source & destination console connections.
"""
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

# Single source of truth for the app version (footer, reports, etc.).
APP_VERSION = "2.0.1"

CONFIG_DIR    = os.path.join(os.path.expanduser("~"), ".s1-command-center")
CONFIG_FILE   = os.path.join(CONFIG_DIR, "contexts.json")
PROFILES_FILE = os.path.join(CONFIG_DIR, "migration_profiles.json")

# ── Optional OS keyring for API tokens ───────────────────────────────────
# When the `keyring` package and a working OS backend are available (macOS
# Keychain / Windows Credential Manager / Secret Service), API tokens are
# stored there instead of in plaintext in contexts.json — the file then holds
# only a sentinel. If keyring is missing or fails, everything degrades to the
# previous plaintext-file behaviour (no lockout). Set S1CC_DISABLE_KEYRING=1
# to force plaintext.
KEYRING_SERVICE = "s1-command-center"
_KEYRING_SENTINEL = "__keyring__"


def _keyring():
    """Return the keyring module if usable, else None. Indirection so tests
    can monkeypatch it."""
    if os.environ.get("S1CC_DISABLE_KEYRING"):
        return None
    try:
        import keyring  # noqa: WPS433
        return keyring
    except Exception:
        return None


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
            return
        # Re-hydrate tokens kept in the OS keyring (sentinel in the file).
        kr = _keyring()
        for c in self.contexts:
            if c.api_token == _KEYRING_SENTINEL:
                tok = ""
                if kr is not None:
                    try:
                        tok = kr.get_password(KEYRING_SERVICE, c.url) or ""
                    except Exception:
                        tok = ""
                c.api_token = tok  # empty → connection will prompt re-auth

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        kr = _keyring()
        rows = []
        for c in self.contexts:
            tok = c.api_token
            file_tok = tok
            # Prefer the OS keyring; fall back to plaintext-in-file on any
            # failure so a missing/locked backend never loses the connection.
            if kr is not None and tok and tok != _KEYRING_SENTINEL:
                try:
                    kr.set_password(KEYRING_SERVICE, c.url, tok)
                    file_tok = _KEYRING_SENTINEL
                except Exception:
                    file_tok = tok
            d = asdict(c)
            d["api_token"] = file_tok
            rows.append(d)
        with open(CONFIG_FILE, "w") as f:
            json.dump(rows, f, indent=2)
        # Even with keyring, the file may hold a plaintext fallback token —
        # lock it to the owner so other local users can't read credentials.
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
        gone = [c for c in self.contexts
                if c.url == url_or_name or c.name == url_or_name]
        before = len(self.contexts)
        self.contexts = [c for c in self.contexts if c.url != url_or_name]
        if len(self.contexts) == before:
            self.contexts = [c for c in self.contexts if c.name != url_or_name]
        # Best-effort: drop any keyring entries for removed contexts.
        kr = _keyring()
        if kr is not None:
            for c in gone:
                try:
                    kr.delete_password(KEYRING_SERVICE, c.url)
                except Exception:
                    pass
        self.save()

    def clear(self):
        """Wipe ALL saved connections (and their keyring tokens) for a clean
        slate. Best-effort on keyring so a missing/locked backend never blocks
        the reset."""
        gone = list(self.contexts)
        self.contexts = []
        kr = _keyring()
        if kr is not None:
            for c in gone:
                try:
                    kr.delete_password(KEYRING_SERVICE, c.url)
                except Exception:
                    pass
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


# ═══════════════════════════════════════════════════════════════════════
#  Migration Profiles — reusable scope + element + mapping selections
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MigrationProfile:
    """A saved, reusable migration setup: which scope to back up, which
    elements to include, and the destination mangle/rename mapping. Holds NO
    secrets (tokens live in contexts.json), so it is safe to share/export."""
    name: str
    description: str = ""
    elements: Optional[list] = None        # subset of BACKUP_ELEMENTS
    levels: Optional[dict] = None          # {"global":bool,"account":bool,...}
    filters: Optional[dict] = None         # {"account":..,"site":..,"group":..}
    mapping: Optional[dict] = None         # mangle/rename rules (name → name)
    created_at: str = ""

    def __post_init__(self):
        # Normalise mutable defaults so callers always get real containers.
        if self.elements is None:
            self.elements = []
        if self.levels is None:
            self.levels = {}
        if self.filters is None:
            self.filters = {}
        if self.mapping is None:
            self.mapping = {}


class ProfileManager:
    """Loads/saves migration profiles. Mirrors ConfigManager's file pattern
    (owner-only dir) but the profile file holds no credentials."""

    def __init__(self):
        self.profiles: list[MigrationProfile] = []
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            os.chmod(CONFIG_DIR, 0o700)
        except OSError:
            pass
        self.load()

    def load(self):
        if not os.path.exists(PROFILES_FILE):
            self.profiles = []
            return
        try:
            with open(PROFILES_FILE, "r") as f:
                raw = json.load(f)
            # Tolerate unknown keys from newer versions by filtering to fields.
            allowed = MigrationProfile.__dataclass_fields__.keys()
            self.profiles = [
                MigrationProfile(**{k: v for k, v in p.items() if k in allowed})
                for p in raw]
        except Exception:
            self.profiles = []

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(PROFILES_FILE, "w") as f:
            json.dump([asdict(p) for p in self.profiles], f, indent=2)
        try:
            os.chmod(PROFILES_FILE, 0o600)
        except OSError:
            pass

    def upsert(self, name: str, *, description: str = "", elements=None,
               levels=None, filters=None, mapping=None,
               created_at: str = "") -> MigrationProfile:
        # A profile's identity is its name (case-insensitive).
        key = name.strip().lower()
        existing = self.get(name)
        self.profiles = [p for p in self.profiles
                         if p.name.strip().lower() != key]
        prof = MigrationProfile(
            name=name.strip(), description=description,
            elements=list(elements or []), levels=dict(levels or {}),
            filters=dict(filters or {}), mapping=dict(mapping or {}),
            # Preserve original creation time on overwrite.
            created_at=created_at or (existing.created_at if existing else ""))
        self.profiles.append(prof)
        self.save()
        return prof

    def remove(self, name: str):
        key = name.strip().lower()
        self.profiles = [p for p in self.profiles
                         if p.name.strip().lower() != key]
        self.save()

    def get(self, name: str) -> Optional[MigrationProfile]:
        key = name.strip().lower()
        return next((p for p in self.profiles
                     if p.name.strip().lower() == key), None)

    def names(self) -> list[str]:
        return [p.name for p in self.profiles]
