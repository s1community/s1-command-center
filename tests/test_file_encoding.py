"""Text files must be written and read as UTF-8 (issue #3).

`open()` without `encoding=` uses the platform default — cp1252 on Windows.
Exporting a STAR rules report died with "'charmap' codec can't encode
characters in position 17809-17810", and any export that *didn't* die wrote
cp1252 bytes into a document declaring `<meta charset="utf-8">`.

macOS and Linux default to UTF-8, so nothing here fails on a developer's
machine — the source guard is what protects the Windows build.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import export_utils  # noqa: E402

APP_MODULES = [
    "app.py", "pages.py", "pages_extra.py", "export_utils.py",
    "config.py", "migtools.py", "tag_audit.py", "s1_api.py",
    "scripts/cleanup_duplicate_star_rules.py",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Calls that aren't the builtin text `open`.
_NOT_BUILTIN = re.compile(r"(Image|webbrowser|self|os|io|gzip|codecs)\.open\(")
# Binary modes handle their own bytes.
_BINARY = re.compile(r"""open\([^)]*['"][rwax]b\+?['"]""")


def _open_calls(text):
    for lineno, line in enumerate(text.splitlines(), 1):
        if "open(" not in line or _NOT_BUILTIN.search(line):
            continue
        if line.lstrip().startswith("#"):
            continue
        if _BINARY.search(line) or "def open" in line:
            continue
        if re.search(r"\bopen\(", line):
            yield lineno, line.strip()


def test_every_text_open_declares_utf8():
    offenders = []
    for rel in APP_MODULES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in _open_calls(f.read()):
                if "encoding=" not in line:
                    offenders.append(f"{rel}:{lineno}: {line}")
    assert not offenders, (
        "open() without encoding= uses cp1252 on Windows and breaks on "
        "non-ASCII (issue #3):\n" + "\n".join(offenders))


def test_a_report_containing_non_ascii_round_trips(tmp_path, monkeypatch):
    # The characters from the bug: a rule name and query with non-ASCII,
    # plus the arrows/dashes the template itself emits.
    rows = [
        {"name": "Détection PowerShell — élevée",
         "s1ql": 'ProcessName = "powershell.exe" AND CmdLine ∋ "–enc"',
         "note": "проверка ✓ 日本語"},
    ]
    out = tmp_path / "report.html"

    monkeypatch.setattr(export_utils.filedialog, "asksaveasfilename",
                        lambda **k: str(out))
    monkeypatch.setattr(export_utils, "cli_log", lambda *a, **k: None)
    monkeypatch.setattr(export_utils.messagebox, "showerror",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("export reported an error")))

    export_utils.export_report("STAR Rules", ["name", "s1ql", "note"], rows)

    raw = out.read_bytes()
    assert b"\xc3\xa9" in raw, "file is not UTF-8 encoded"
    text = raw.decode("utf-8")
    assert "Détection PowerShell — élevée" in text
    assert "проверка ✓ 日本語" in text
    assert 'charset="utf-8"' in text


def test_a_json_export_containing_non_ascii_round_trips(tmp_path, monkeypatch):
    rows = [{"name": "Ölfilter", "value": "ünïcödé"}]
    out = tmp_path / "data.json"

    monkeypatch.setattr(export_utils.filedialog, "asksaveasfilename",
                        lambda **k: str(out))
    monkeypatch.setattr(export_utils, "cli_log", lambda *a, **k: None)

    export_utils.export_report("Anything", ["name", "value"], rows)

    with open(out, encoding="utf-8") as f:
        assert json.load(f) == rows


def test_the_windows_default_encoding_would_have_failed():
    # Proves the bug was real rather than theoretical: the same content
    # through a cp1252 writer raises exactly what the user reported.
    buf = io.BytesIO()
    writer = io.TextIOWrapper(buf, encoding="cp1252")
    try:
        writer.write("Détection — élevée ✓")
        writer.flush()
    except UnicodeEncodeError as exc:
        assert "charmap" in str(exc)
    else:
        raise AssertionError("expected cp1252 to reject this content")
