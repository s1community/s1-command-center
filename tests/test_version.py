"""Version wiring + sync checks.

Guards two regressions that shipped in v2.0.1/v2.0.2:

1. `app.py` referenced `APP_VERSION` in the sidebar footer without importing
   it, so the app crashed on launch with `NameError: name 'APP_VERSION' is
   not defined`. Importing `app`/`pages` and reading `.APP_VERSION` fails the
   same way (AttributeError) if the import is missing — no display needed.
2. The version is duplicated across config.py, version_info.txt and
   installer/windows.iss; they must not drift.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_config_has_version():
    import config
    assert isinstance(config.APP_VERSION, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", config.APP_VERSION), config.APP_VERSION


def test_app_imports_version():
    # Fails with AttributeError if app.py forgot to import APP_VERSION — the
    # exact bug that crashed the app on startup.
    import config
    import app
    assert app.APP_VERSION == config.APP_VERSION


def test_pages_imports_version():
    import config
    import pages
    assert pages.APP_VERSION == config.APP_VERSION


def test_version_files_in_sync():
    import config
    v = config.APP_VERSION

    vinfo = open(os.path.join(ROOT, "version_info.txt")).read()
    file_ver = re.search(r"FileVersion',\s*u'([\d.]+)'", vinfo).group(1)
    prod_ver = re.search(r"ProductVersion',\s*u'([\d.]+)'", vinfo).group(1)
    filevers = re.search(r"filevers=\(([\d, ]+)\)", vinfo).group(1)
    filevers_dotted = ".".join(p.strip() for p in filevers.split(","))
    assert file_ver == f"{v}.0", file_ver
    assert prod_ver == f"{v}.0", prod_ver
    assert filevers_dotted == f"{v}.0", filevers_dotted

    iss = open(os.path.join(ROOT, "installer", "windows.iss")).read()
    iss_ver = re.search(r'#define\s+AppVersion\s+"([\d.]+)"', iss).group(1)
    assert iss_ver == v, iss_ver
