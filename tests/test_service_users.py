"""Service users are migrated, not just inventoried.

Landeshauptstadt München (v2.2.8, 2026-09): the backup captured 15 service
users at account level and the restore created none of them and reported
nothing — `service_users` was on the "captured for audit only" list, so the
element checkbox was a no-op.

The API *token* still cannot be migrated (SentinelOne reveals a token exactly
once, at creation, so it is never in the backup), but the service user itself
is creatable. These tests pin the payload: no source IDs, scope and role
rebuilt from names, and expiry carried over.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import (
    RestorePage,
    _build_service_user_payload,
    _unresolved_service_user_scopes,
)

# Shape as returned by GET /service-users on a real console.
SRC_USER = {
    "apiToken": {"createdAt": "2023-12-19T23:42:51.087759Z",
                 "expiresAt": "2025-10-30T23:42:15Z"},
    "createdAt": "2023-12-19T23:42:50.997692Z",
    "createdBy": {"id": "1599626233933122097", "name": "Posh Gardiye"},
    "description": "Darktrace Integration",
    "id": "1843820828304888119",
    "lastActivation": "2025-10-30T23:32:43.104085Z",
    "name": "darktrace.au",
    "scope": "site",
    "scopeRoles": [{
        "accountName": "Beijer Ref AB",
        "id": "1535334414585508710",
        "name": "Australia",
        "roleId": "1407838462433820674",
        "roleName": "Admin",
        "roles": ["Admin"],
    }],
}

DEST_SITES = {"australia": "9001"}
DEST_ROLES = {"admin": "7001"}


def test_payload_keeps_the_identity_fields():
    out = _build_service_user_payload(SRC_USER, "acct-1", DEST_SITES,
                                      DEST_ROLES)
    assert out["name"] == "darktrace.au"
    assert out["description"] == "Darktrace Integration"


def test_scope_and_role_are_remapped_by_name():
    out = _build_service_user_payload(SRC_USER, "acct-1", DEST_SITES,
                                      DEST_ROLES)
    assert out["scope"] == "site"
    assert out["scopeRoles"] == [{"id": "9001", "roleId": "7001"}]


def test_no_source_side_ids_or_audit_fields_leak_into_the_payload():
    out = _build_service_user_payload(SRC_USER, "acct-1", DEST_SITES,
                                      DEST_ROLES)
    for banned in ("id", "createdAt", "createdBy", "updatedAt", "updatedBy",
                   "lastActivation", "apiToken"):
        assert banned not in out
    flat = repr(out)
    assert SRC_USER["id"] not in flat
    assert SRC_USER["scopeRoles"][0]["id"] not in flat
    assert SRC_USER["scopeRoles"][0]["roleId"] not in flat


def test_expiry_is_carried_over_from_the_token_metadata():
    out = _build_service_user_payload(SRC_USER, "acct-1", DEST_SITES,
                                      DEST_ROLES)
    assert out["expiresAt"] == "2025-10-30T23:42:15Z"
    assert "unlimitedExpiry" not in out


def test_a_user_without_an_expiry_is_created_unlimited():
    src = dict(SRC_USER)
    src.pop("apiToken")
    out = _build_service_user_payload(src, "acct-1", DEST_SITES, DEST_ROLES)
    assert out["unlimitedExpiry"] is True
    assert "expiresAt" not in out


def test_an_unresolvable_site_falls_back_to_the_account_scope():
    # Sending the source's site ID would earn an opaque 400; creating the
    # user at account scope leaves the operator something to re-scope.
    out = _build_service_user_payload(SRC_USER, "acct-1", {}, DEST_ROLES)
    assert out["scope"] == "account"
    assert out["scopeRoles"] == [{"id": "acct-1"}]


def test_an_unresolvable_role_falls_back_to_the_account_scope():
    out = _build_service_user_payload(SRC_USER, "acct-1", DEST_SITES, {})
    assert out["scope"] == "account"
    assert out["scopeRoles"] == [{"id": "acct-1"}]


def test_only_the_resolvable_scope_assignments_are_kept():
    src = dict(SRC_USER)
    src["scopeRoles"] = [
        {"name": "Australia", "roleName": "Admin"},
        {"name": "Ghost Site", "roleName": "Admin"},
    ]
    out = _build_service_user_payload(src, "acct-1", DEST_SITES, DEST_ROLES)
    assert out["scopeRoles"] == [{"id": "9001", "roleId": "7001"}]


def test_an_account_scoped_source_user_maps_onto_the_dest_account():
    src = {"name": "acct-svc", "scope": "account",
           "scopeRoles": [{"name": "Beijer Ref AB",
                           "accountName": "Beijer Ref AB",
                           "roleName": "Admin"}]}
    out = _build_service_user_payload(src, "acct-1", {}, DEST_ROLES)
    assert out["scopeRoles"] == [{"id": "acct-1", "roleId": "7001"}]


def test_missing_scopes_are_reported_by_name():
    src = dict(SRC_USER)
    src["scopeRoles"] = [
        {"name": "Australia", "roleName": "Admin"},
        {"name": "Ghost Site", "roleName": "Threat Hunter"},
    ]
    assert _unresolved_service_user_scopes(src, DEST_SITES, DEST_ROLES) == \
        ["Ghost Site/Threat Hunter"]


def test_nothing_is_reported_missing_when_everything_resolves():
    assert _unresolved_service_user_scopes(SRC_USER, DEST_SITES,
                                           DEST_ROLES) == []


def test_the_builder_tolerates_junk():
    out = _build_service_user_payload({}, "", {}, {})
    assert out["name"] == ""
    assert _build_service_user_payload({"scopeRoles": ["nope", None]},
                                       "acct-1", {}, {})["scope"] == "account"


# ── wiring ──────────────────────────────────────────────────────────────

def test_the_restore_loop_actually_creates_service_users():
    src = inspect.getsource(RestorePage._run_restore)
    assert '"service_users" in elements' in src
    assert "create_service_user" in src
    assert "_build_service_user_payload" in src


def test_the_operator_is_told_the_token_is_not_migrated():
    # A silently token-less service user breaks whatever integration used it.
    src = inspect.getsource(RestorePage._run_restore)
    assert "tokens are NOT migrated" in src
