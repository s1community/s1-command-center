"""
SentinelOne API Client — handles auth, pagination, backup/restore data retrieval.
"""
import re
import requests
import time as _time
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, List, Optional, Tuple
from requests.adapters import HTTPAdapter


def _auth_header(token: str) -> str:
    """Return 'Bearer <token>' for JWTs, 'ApiToken <token>' for API keys."""
    if re.match(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$', token.strip()):
        return f"Bearer {token}"
    return f"ApiToken {token}"


class S1APIError(Exception):
    def __init__(self, message: str, status_code: int = 0, detail: str = ""):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)


# The `type` a unified endpoint tag carries. GET /agents/tags returns
# "agents" on every tag it hands back, and POST /tag-manager validates the
# field, so a guessed value ("endpoints") is rejected for every tag on every
# scope — which is exactly what the beijerrefab migration hit.
ENDPOINT_TAG_TYPE = "agents"


def created_something(resp: dict) -> bool:
    """Did a create response describe an object that now exists?

    A 2xx is not proof on its own: ``POST /tag-manager`` answers 200 to a
    body it does not understand and stores nothing, which is how a restore
    can report "150 new" against a console that ends up with none. A
    response counts as a real create when it carries an object, a non-empty
    list, or a positive ``affected`` count.
    """
    data = (resp or {}).get("data")
    if isinstance(data, dict) and "affected" in data:
        try:
            return int(data.get("affected") or 0) > 0
        except (TypeError, ValueError):
            return False
    return bool(data)


class S1API:
    API_PREFIX = "/web/api/v2.1"

    def __init__(self, base_url: str, api_token: str, pool_maxsize: int = 32,
                 verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.verify = verify_ssl
        if not verify_ssl:
            # Suppress the per-request InsecureRequestWarning spam when the
            # user has explicitly opted into ignoring SSL errors.
            try:
                from urllib3.exceptions import InsecureRequestWarning
                import urllib3
                urllib3.disable_warnings(InsecureRequestWarning)
            except Exception:
                pass
        adapter = HTTPAdapter(
            pool_connections=pool_maxsize,
            pool_maxsize=pool_maxsize,
            pool_block=False,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "Authorization": _auth_header(self.api_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        # Rate-limit telemetry. A big backup/restore that slows down is almost
        # always the API throttling us (HTTP 429); these counters let the UI
        # explain that instead of looking frozen. `on_throttle`, if set by the
        # app, is called with a small dict on each 429 backoff.
        self.throttle_events = 0
        self.throttle_wait_s = 0.0
        self.on_throttle = None

    def throttle_stats(self) -> dict:
        """Snapshot of rate-limit backoff seen so far on this connection."""
        return {"events": self.throttle_events,
                "wait_seconds": round(self.throttle_wait_s, 1)}

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.API_PREFIX}"

    # ── HTTP primitives ────────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None,
                 body: Optional[dict] = None, retries: int = 4) -> dict:
        url = f"{self.api_url}{endpoint}"
        last_exc = None
        for attempt in range(retries):
            try:
                if attempt > 0:
                    _time.sleep(1.5 * attempt)
                resp = self.session.request(method, url, params=params, json=body, timeout=120)
                if resp.status_code in (200, 201):
                    return resp.json()
                detail = ""
                try:
                    resp_body = resp.json() or {}
                    errs = resp_body.get("errors") or []
                    if errs:
                        # Concatenate every error's title + detail + code so
                        # the operator (and the error-classifier) can see the
                        # real reason. S1 frequently populates `title` and
                        # leaves `detail` blank for validation errors.
                        parts = []
                        for er in errs:
                            t = (er.get("title") or "").strip()
                            d = (er.get("detail") or "").strip()
                            c = er.get("code")
                            chunk = " :: ".join(x for x in (t, d) if x)
                            if c and chunk:
                                chunk = f"{chunk} (code {c})"
                            elif c:
                                chunk = f"code {c}"
                            if chunk:
                                parts.append(chunk)
                        detail = " | ".join(parts) or str(resp_body)
                    else:
                        # Some endpoints return {"message": "..."} or a bare
                        # string — keep whatever is there.
                        detail = resp_body.get("message") \
                                 or resp_body.get("error") or resp.text
                except Exception:
                    detail = resp.text or ""
                # Retry on 429 (rate limit) and 5xx (server errors)
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    wait = int(retry_after) if (retry_after
                                                and retry_after.isdigit()) else 0
                    if resp.status_code == 429:
                        # Track throttling so the UI can show why a run is slow.
                        self.throttle_events += 1
                        self.throttle_wait_s += wait or (1.5 * (attempt + 1))
                        if callable(self.on_throttle):
                            try:
                                self.on_throttle({
                                    "endpoint": endpoint,
                                    "retry_after": wait,
                                    "events": self.throttle_events})
                            except Exception:
                                pass
                    if wait:
                        _time.sleep(wait)
                    if attempt < retries - 1:
                        continue
                raise S1APIError(f"{method} {endpoint} → {resp.status_code}",
                                 resp.status_code, detail)
            except S1APIError:
                raise
            except (requests.exceptions.ContentDecodingError, zlib.error) as e:
                last_exc = ("response decoding failed; console returned invalid "
                            f"compressed data: {e}")
                if attempt < retries - 1:
                    continue
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                    ConnectionResetError, ConnectionAbortedError) as e:
                last_exc = e
                if attempt < retries - 1:
                    continue
        raise S1APIError(f"{method} {endpoint} failed after {retries} attempts: {last_exc}",
                         0, str(last_exc))

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        return self._request("POST", endpoint, params=params, body=body)

    def _put(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        return self._request("PUT", endpoint, params=params, body=body)

    def get_data(self, endpoint: str, params: Optional[dict] = None) -> Any:
        return self._get(endpoint, params).get("data", {})

    def get_all(self, endpoint: str, params: Optional[dict] = None,
                data_field: str = "data", limit: int = 200,
                max_items: int = 0, progress_cb=None) -> list[dict]:
        results: list[dict] = []
        q = dict(params or {})
        q["limit"] = limit
        cursor: Optional[str] = None
        while True:
            if cursor:
                q["cursor"] = cursor
            body = self._get(endpoint, q)
            page = body.get(data_field) or []
            results.extend(page)
            total = body.get("pagination", {}).get("totalItems", len(results))
            if progress_cb:
                progress_cb(len(results), total)
            if max_items and len(results) >= max_items:
                return results[:max_items]
            cursor = body.get("pagination", {}).get("nextCursor")
            if not cursor:
                break
        return results

    # ── parallel fan-out ──────────────────────────────────────────────

    def get_many(self, calls: list[tuple], max_workers: int = 8) -> list[dict]:
        """Run many independent GETs in parallel using a thread pool.

        Args:
            calls: list of (endpoint, params) tuples
            max_workers: thread pool size (default 8)

        Returns:
            list of result dicts in input order, each with:
            {"endpoint", "params", "ok", "data", "error", "elapsed_ms"}
        """
        calls = list(calls)
        results: list[Optional[dict]] = [None] * len(calls)

        def _one(i: int, endpoint: str, params: Optional[dict]):
            t0 = _time.time()
            try:
                body = self._get(endpoint, params)
                return i, {"endpoint": endpoint, "params": params, "ok": True,
                           "data": body, "error": None,
                           "elapsed_ms": (_time.time() - t0) * 1000.0}
            except Exception as e:
                return i, {"endpoint": endpoint, "params": params, "ok": False,
                           "data": None, "error": str(e),
                           "elapsed_ms": (_time.time() - t0) * 1000.0}

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_one, i, ep, p) for i, (ep, p) in enumerate(calls)]
            for f in as_completed(futs):
                i, r = f.result()
                results[i] = r
        return results

    # ── quick helpers ──────────────────────────────────────────────────

    def get_my_user(self) -> dict:
        return self.get_data("/private/my-user")

    def get_accounts(self, **kw) -> list[dict]:
        return self.get_all("/accounts", params={"states": "active", "sortBy": "name", "sortOrder": "asc"}, **kw)

    def get_account_by_id(self, account_id: str) -> Optional[dict]:
        """Fetch a single account by exact ID. Returns None if not found or inaccessible."""
        results = self.get_all("/accounts", params={"ids": account_id})
        return next((a for a in results if str(a.get("id")) == str(account_id)), None)

    def get_sites(self, params: Optional[dict] = None, **kw) -> list[dict]:
        # S1 Sites API returns nested structure — try multiple formats
        results: list[dict] = []
        q = dict(params or {})
        q["limit"] = 200
        cursor = None
        while True:
            if cursor:
                q["cursor"] = cursor
            body = self._get("/sites", q)
            page = []
            # Try: body["data"]["sites"] (nested dict)
            data_obj = body.get("data", {})
            if isinstance(data_obj, dict):
                page = data_obj.get("sites") or []
            # Try: body["sites"] (top-level)
            if not page:
                page = body.get("sites") or []
            # Try: body["data"] as list directly
            if not page and isinstance(data_obj, list):
                page = data_obj
            results.extend(page)
            cursor = body.get("pagination", {}).get("nextCursor")
            if not cursor:
                break
        return results

    def get_groups(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/groups", params=params, **kw)

    def get_agents(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/agents", params=params, **kw)

    # ── scope helpers ──────────────────────────────────────────────────

    @staticmethod
    def scope_filter(scope_type: str, scope_id: str) -> dict:
        if scope_type == "global":
            return {"tenant": "true"}
        elif scope_type == "account":
            return {"accountIds": scope_id}
        elif scope_type == "site":
            return {"siteIds": scope_id}
        elif scope_type == "group":
            return {"groupIds": scope_id}
        return {}

    # ── backup: read config from a node ────────────────────────────────

    def get_exclusions(self, scope: dict, excl_type: str) -> list[dict]:
        p = dict(scope)
        p["type"] = excl_type
        return self.get_all("/exclusions", params=p)

    def get_unified_exclusions(self, scope: dict) -> list[dict]:
        return self.get_all("/unified-exclusions", params=scope)

    def get_blocklist(self, scope: dict) -> list[dict]:
        p = dict(scope)
        p["type"] = "black_hash"
        return self.get_all("/restrictions", params=p)

    def get_policy(self, scope_type: str, scope_id: str = "") -> dict:
        ep = {"global": "/tenant/policy", "account": f"/accounts/{scope_id}/policy",
              "site": f"/sites/{scope_id}/policy", "group": f"/groups/{scope_id}/policy"}.get(scope_type)
        return self.get_data(ep) if ep else {}

    def get_firewall_rules(self, scope: dict) -> list[dict]:
        return self.get_all("/firewall-control", params=scope)

    def get_firewall_config(self, scope: dict) -> dict:
        return self.get_data("/firewall-control/configuration", params=scope)

    def get_tags(self, tag_type: str, scope: dict) -> list[dict]:
        p = dict(scope)
        p["type"] = tag_type
        return self.get_all("/tags", params=p)

    def get_star_rules(self, scope: dict) -> list[dict]:
        return self.get_all("/cloud-detection/rules", params=scope)

    def get_device_control_rules(self, scope: dict) -> list[dict]:
        return self.get_all("/device-control", params=scope)

    def get_device_control_config(self, scope: dict) -> dict:
        return self.get_data("/device-control/configuration", params=scope)

    def get_saved_filters(self, scope: dict) -> list[dict]:
        return self.get_all("/filters", params=scope)

    def get_nq_rules(self, scope: dict) -> list[dict]:
        return self.get_all("/network-quarantine-control", params=scope)

    def get_nq_config(self, scope: dict) -> dict:
        return self.get_data("/network-quarantine-control/configuration", params=scope)

    def get_locations(self, scope: dict) -> list[dict]:
        return self.get_all("/locations", params=scope)

    def get_system_info(self) -> dict:
        return self.get_data("/system/info")

    def get_policy_overrides(self, scope: dict) -> list[dict]:
        return self.get_all("/policy/overrides", params=scope)

    # ── config / policy overrides ──────────────────────────────────────
    # Endpoints per S1 spec — note the path is SINGULAR (/config-override).

    def get_config_overrides(self, scope: dict) -> list[dict]:
        """GET /config-override — list overrides matching the scope filter."""
        return self.get_all("/config-override", params=scope)

    def create_config_override(self, scope: dict, data: dict) -> dict:
        """POST /config-override — create a new override on the destination
        scope. S1 requires the scope filter embedded in the body alongside
        the override data.
        Requires Policy Override.create. Use support-actions/config to get
        the complete syntax (Global / Support users only)."""
        return self._post("/config-override", body={
            "filter": scope, "data": data})

    def update_config_override(self, override_id: str, data: dict) -> dict:
        """PUT /config-override/{id} — change the value of one override."""
        return self._put(f"/config-override/{override_id}",
                         body={"data": data})

    def delete_config_override(self, override_id: str) -> dict:
        """DELETE /config-override/{id} — delete one override by ID."""
        return self._delete(f"/config-override/{override_id}")

    def delete_config_overrides(self, ids: list[str]) -> dict:
        """DELETE /config-override — bulk delete overrides matching filter."""
        return self._delete("/config-override", body={
            "filter": {"ids": ids}})

    # ── locations ──────────────────────────────────────────────────────

    def create_location(self, scope: dict, data: dict) -> dict:
        return self._post("/locations", body={"filter": scope, "data": data})

    def delete_locations(self, ids: list[str]) -> dict:
        return self._delete("/locations", body={"filter": {"ids": ids}})

    # ── webhooks (notification channels) ───────────────────────────────
    # There is NO webhook resource in the v2.1 management API. The whole
    # `settings` tag is active-directory, microsoft, notifications,
    # recipients, sms, smtp, sso and syslog — no webhooks — and no other
    # tag exposes them either. `/notification-webhooks` was invented: it
    # 404s, and the backup recorded that as "n/a", so it read as captured.
    # Webhooks have to be recreated by hand on the destination.

    WEBHOOKS_UNSUPPORTED = (
        "SentinelOne's v2.1 API exposes no webhook endpoint — webhooks must "
        "be recreated manually on the destination console")

    # ── Singularity Marketplace (installed integrations inventory) ─────
    # NOTE: Marketplace applications cannot be re-installed via API — each
    # one needs its own OAuth handshake / credentials. We capture them
    # as an inventory only so the operator knows what to re-install
    # manually on the destination.

    def get_marketplace_apps(self, scope: dict) -> list[dict]:
        return self.get_all("/singularity-marketplace/applications",
                            params=scope)

    # ── Scheduled reports ──────────────────────────────────────────────

    # Scheduled reports are /report-tasks. `/reports` is the generated
    # report list, and `/reports/scheduled` does not exist at all.

    def get_scheduled_reports(self, scope: dict) -> list[dict]:
        return self.get_all("/report-tasks", params=scope)

    def create_scheduled_report(self, scope: dict, data: dict) -> dict:
        return self._post("/report-tasks", body={
            "filter": scope, "data": data})

    def delete_scheduled_report(self, report_id: str) -> dict:
        # This resource has no DELETE verb — removal is a POST with the ids
        # in a filter envelope.
        return self._post("/reports/delete-tasks",
                          body={"filter": {"ids": [report_id]}})

    # ── notification / integration settings ────────────────────────────

    def get_notification_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/notifications", params=scope)

    def set_notification_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/notifications", body={
            "filter": scope, "data": data})

    def get_notification_recipients(self, scope: dict) -> list[dict]:
        return self.get_all("/settings/recipients", params=scope)

    def set_notification_recipients(self, scope: dict, data: list[dict]) -> dict:
        # S1 returns `data: dict_values(['emails']): Unknown field` when
        # we wrap the list in `{"emails": data}`. The PUT endpoint takes
        # the raw list (matching the shape `get` returns). If the tenant
        # rejects the bulk PUT we fall back to per-recipient POSTs.
        if not data:
            return {}
        try:
            return self._put("/settings/recipients", body={
                "filter": scope, "data": data})
        except S1APIError as e:
            # ANY 400 here is the tenant disagreeing about the body shape, so
            # every one of them has to reach the fallbacks below. Matching on
            # the phrase "unknown field" was too narrow: the beijerrefab and
            # Landeshauptstadt München consoles both answer "Field data in
            # request body must be valid class …NotificationRecipientDto"
            # (i.e. `data` must be ONE recipient, not a list), which never
            # matched, so the per-recipient path that would have worked was
            # never tried and recipients failed on all 43 scopes.
            if e.status_code != 400:
                raise
            # Schema-shape fallback: try the singular field name.
            try:
                return self._put("/settings/recipients", body={
                    "filter": scope, "data": {"recipients": data}})
            except S1APIError:
                # Last resort: post each recipient individually so the
                # ones we *can* migrate get through and the broken ones
                # surface their own error with a name in the payload.
                ok = 0
                last_exc = None
                for item in data:
                    try:
                        self._post("/settings/recipients", body={
                            "filter": scope, "data": item})
                        ok += 1
                    except S1APIError as ie:
                        last_exc = ie
                if ok == 0 and last_exc is not None:
                    raise last_exc
                return {"data": {"affected": ok}}

    # ── SSO settings ───────────────────────────────────────────────────

    def get_sso_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/sso", params=scope)

    def set_sso_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/sso", body={
            "filter": scope, "data": data})

    # ── SMTP settings ──────────────────────────────────────────────────

    def get_smtp_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/smtp", params=scope)

    def set_smtp_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/smtp", body={
            "filter": scope, "data": data})

    # ── Syslog settings ────────────────────────────────────────────────

    def get_syslog_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/syslog", params=scope)

    def set_syslog_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/syslog", body={
            "filter": scope, "data": data})

    # ── AD settings ────────────────────────────────────────────────────

    def get_ad_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/active-directory", params=scope)

    def set_ad_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/active-directory", body={
            "filter": scope, "data": data})

    # ── RBAC roles ─────────────────────────────────────────────────────

    def create_role(self, data: dict, scope_filter: Optional[dict] = None) -> dict:
        # S1 `RbacCreateRoleSchema` requires a top-level `filter` that names the
        # target scope (accountIds / siteIds / tenant); the scope must NOT be
        # embedded in `data` (it rejects `scope`/`accountIds` there as "Unknown
        # field"). Mirrors the {filter, data} envelope used by firewall/AD.
        body: dict = {"data": data}
        if scope_filter:
            body["filter"] = scope_filter
        return self._post("/rbac/role", body=body)

    def get_role_template(self, params: Optional[dict] = None) -> dict:
        # "Get template for new role" is GET /rbac/role (scoped by
        # accountIds/siteIds/tenant), NOT /rbac/role/template. The returned
        # object is the create-ready `data` skeleton for that scope, so it
        # already carries the destination's licensed permission taxonomy.
        return self.get_data("/rbac/role", params=params)

    # ── service users ──────────────────────────────────────────────────

    def get_service_users(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/service-users", params=params, **kw)

    def create_service_user(self, data: dict) -> dict:
        return self._post("/service-users", body={"data": data})

    # ── log collection rules ───────────────────────────────────────────

    def get_log_collection_rules(self, scope: dict) -> list[dict]:
        # /log-collection/rules — NOT /log-collection-rules, which 404s.
        # includeParents / includeChildren both default to false, which is
        # what we want: each scope backs up only the rules it owns.
        return self.get_all("/log-collection/rules", params=scope)

    def create_log_collection_rule(self, data: dict) -> dict:
        return self._post("/log-collection/rules", body={"data": data})

    # ── upgrade / auto-upgrade policies ────────────────────────────────

    # This resource does not behave like the rest of the API. The path is
    # /upgrade-policy/policies (not /agents-policy/...), scope is given as
    # scopeLevel + scopeId query params rather than the usual
    # accountIds/siteIds filter, paging is skip/limit rather than a cursor,
    # and osType is REQUIRED — so every OS family has to be queried
    # separately to see all the policies. get_all() fits none of that.
    UPGRADE_OS_TYPES = ("windows", "linux", "macos")
    _UPGRADE_PAGE = 100

    def get_auto_upgrade_policies(self, scope_level: str,
                                  scope_id: str = "") -> list[dict]:
        level = "tenant" if scope_level == "global" else scope_level
        out: list[dict] = []
        for os_type in self.UPGRADE_OS_TYPES:
            skip = 0
            while True:
                q = {"scopeLevel": level, "osType": os_type,
                     "limit": self._UPGRADE_PAGE, "skip": skip,
                     "sortBy": "priority", "sortOrder": "asc"}
                if scope_id:
                    q["scopeId"] = str(scope_id)
                page = self._get("/upgrade-policy/policies", q).get("data") or []
                for pol in page:
                    pol.setdefault("osType", os_type)
                out.extend(page)
                if len(page) < self._UPGRADE_PAGE:
                    break
                skip += self._UPGRADE_PAGE
        return out

    def create_auto_upgrade_policy(self, data: dict) -> dict:
        # POST /upgrade-policy/policy (SINGULAR) adds a policy.
        # POST /upgrade-policy/policies (PLURAL) deactivates every policy in
        # the scope. Never point this at the plural path.
        return self._post("/upgrade-policy/policy", body={"data": data})

    # ── endpoint tags (unified / "Tag Manager") ────────────────────────
    # These are key/value endpoint tags, NOT the named /tags objects used by
    # firewall, network-quarantine and device-inventory. There is no
    # /endpoint-tags route in the v2.1 API: listing goes through
    # GET /agents/tags and creating through POST /tag-manager.

    def get_endpoint_tags(self, scope: dict) -> list[dict]:
        return self.get_all("/agents/tags", params=scope)

    @staticmethod
    def _created_something(resp: dict) -> bool:
        """Did a create response describe an object that now exists?"""
        return created_something(resp)

    def endpoint_tag_exists(self, data: dict,
                            scope: dict | None = None) -> Optional[bool]:
        """Is this endpoint tag on the console? ``None`` = couldn't tell.

        Used to confirm a create whose response didn't echo the tag. The
        answer has to be three-valued: treating "I couldn't check" as "not
        created" is what would make a retry duplicate the tag.

        The narrow ``key__contains`` read is tried first and the whole scope
        second, so a console that doesn't support that filter still gets a
        real answer instead of an unnecessary "couldn't confirm".
        """
        key = data.get("key")
        if not key:
            return None
        want = data.get("value")
        attempts = [{**(scope or {}), "key__contains": key}, dict(scope or {})]
        for params in attempts:
            try:
                found = self.get_all("/agents/tags", params=params)
            except S1APIError:
                continue
            for tag in found or []:
                if tag.get("key") != key:
                    continue
                if not want or str(tag.get("value") or "") == str(want):
                    return True
            return False
        return None

    def create_endpoint_tag(self, data: dict, scope: dict | None = None) -> dict:
        """Create one unified endpoint tag, or raise — never a silent no-op.

        One request, one error. ``POST /tag-manager`` takes a single tag
        object in ``data`` — ``type``, ``key`` and ``value`` are all required
        — and the target scope in ``filter``. Earlier versions followed a
        rejection by re-sending the tag inside a list and then inside
        ``data.tags``, and reported whichever error came last: the console's
        real complaint about the real request ("type: invalid") was replaced
        by its complaint about a guess ("key, value, type: missing"), which
        is how a 100%-failed migration produced an error nobody could act on.

        A 2xx is still not taken as proof. A create the console answers
        without echoing the tag is read back before it counts, because a
        request that stores nothing must not be reported as a success.
        """
        key = data.get("key") or data.get("name") or "?"
        body = {"data": data, "filter": scope} if scope else {"data": data}
        try:
            resp = self._post("/tag-manager", body=body)
        except S1APIError as exc:
            # A console that rejects the scope envelope itself gets one retry
            # without it — a 400 stored nothing, so this cannot duplicate.
            if not (scope and exc.status_code == 400
                    and "filter" in f"{exc.message} {exc.detail}".lower()):
                raise
            resp = self._post("/tag-manager", body={"data": data})

        if self._created_something(resp):
            return resp
        exists = self.endpoint_tag_exists(data, scope)
        if exists is True:
            return resp
        if exists is None:
            raise S1APIError(
                f"could not confirm endpoint tag '{key}' was created", 0,
                "The console accepted the request with an empty response and "
                "the tag could not be read back, so it is unsafe to retry — "
                "that would risk creating it twice. Check the tag on the "
                "console, or open Tags (Operations → Inventory) and run "
                "'Diagnose endpoint tags'.")
        raise S1APIError(
            f"POST /tag-manager accepted endpoint tag '{key}' but created "
            f"nothing", 0,
            "The console returned success and the tag is not there "
            "afterwards. This is what a token without the 'Tag "
            "Management.create' permission looks like on this route. Open "
            "Tags (Operations → Inventory) and run 'Diagnose endpoint tags' "
            "to confirm.")

    # ── NQ control: create/set ─────────────────────────────────────────

    def create_nq_rule(self, scope: dict, data: dict) -> dict:
        return self._post("/network-quarantine-control", body={
            "filter": scope, "data": data})

    def set_nq_config(self, scope: dict, data: dict) -> dict:
        return self._put("/network-quarantine-control/configuration", body={
            "filter": scope, "data": data})

    # ── locations: create ──────────────────────────────────────────────

    def get_gateways(self, scope: dict) -> list[dict]:
        return self.get_all("/gateways", params=scope)

    # ── restore: write config to a node ────────────────────────────────

    def set_policy(self, scope_type: str, scope_id: str, policy: dict) -> dict:
        ep = {"global": "/tenant/policy", "account": f"/accounts/{scope_id}/policy",
              "site": f"/sites/{scope_id}/policy", "group": f"/groups/{scope_id}/policy"}.get(scope_type)
        return self._put(ep, body={"data": policy}) if ep else {}

    def create_exclusion(self, scope: dict, data: dict) -> dict:
        return self._post("/exclusions", body={"filter": scope, "data": data})

    def create_unified_exclusion(self, scope: dict, data: dict) -> dict:
        return self._post("/unified-exclusions", body={"filter": scope, "data": data})

    def create_restriction(self, scope: dict, data: dict) -> dict:
        return self._post("/restrictions", body={"filter": scope, "data": data})

    def create_firewall_rule(self, scope: dict, data: dict) -> dict:
        return self._post("/firewall-control", body={"filter": scope, "data": data})

    def reorder_firewall_rules(self, scope: dict, rule_ids: list[str]) -> dict:
        return self._put("/firewall-control/reorder", body={
            "filter": scope, "data": {"ids": rule_ids}})

    def set_firewall_config(self, scope: dict, data: dict) -> dict:
        return self._put("/firewall-control/configuration", body={"filter": scope, "data": data})

    def create_tag(self, scope: dict, data: dict) -> dict:
        return self._post("/tags", body={"filter": scope, "data": data})

    def create_device_control_rule(self, scope: dict, data: dict) -> dict:
        return self._post("/device-control", body={"filter": scope, "data": data})

    def reorder_device_control_rules(self, scope: dict, rule_ids: list[str]) -> dict:
        return self._put("/device-control/reorder", body={
            "filter": scope, "data": {"ids": rule_ids}})

    def set_device_control_config(self, scope: dict, data: dict) -> dict:
        return self._put("/device-control/configuration", body={"filter": scope, "data": data})

    def create_saved_filter(self, scope: dict, data: dict) -> dict:
        return self._post("/filters", body={"filter": scope, "data": data})

    def create_star_rule(self, scope: dict, data: dict) -> dict:
        return self._post("/cloud-detection/rules", body={"filter": scope, "data": data})

    def delete_star_rules(self, ids: list[str]) -> dict:
        """DELETE /cloud-detection/rules — bulk-delete STAR custom-detection
        rules by ID. Body is {"filter": {"ids": [...]}, "data": {}}."""
        return self._delete("/cloud-detection/rules",
                            body={"filter": {"ids": [str(i) for i in ids]},
                                  "data": {}})

    # ── create site / group ──────────────────────────────────────────────

    def create_site(self, account_id: str, data: dict) -> dict:
        body = {"data": dict(data)}
        body["data"]["accountId"] = account_id
        return self._post("/sites", body=body)

    def update_site(self, site_id: str, data: dict) -> dict:
        return self._put(f"/sites/{site_id}", body={"data": data})

    def create_group(self, site_id: str, data: dict) -> dict:
        body = {"data": dict(data)}
        body["data"]["siteId"] = site_id
        return self._post("/groups", body=body)

    def update_group(self, group_id: str, data: dict) -> dict:
        """PUT /groups/{id} — update an existing group (name, type,
        filterId, rank, description, inherits, registrationToken). Used
        on restore to overwrite a destination group with the source's
        settings so e.g. dynamic groups don't get stuck as static."""
        return self._put(f"/groups/{group_id}", body={"data": dict(data)})

    def move_group_to_pinned(self, group_id: str) -> dict:
        """Convert an existing static/dynamic group into a Pinned group.

        S1 has shipped a few different shapes for this operation across
        versions. We try them in order and return the first one that
        doesn't 404 / 4xx-unknown-route. Any 4xx from a known endpoint
        is raised so the caller can log the real reason.
        """
        attempts = [
            ("POST", f"/groups/{group_id}/move-to-pinned", {}),
            ("POST", f"/groups/{group_id}/move-to-pin", {}),
            ("POST", f"/groups/{group_id}/pin", {}),
            ("PUT",  f"/groups/{group_id}",
                {"data": {"type": "pinned", "name": None}}),
        ]
        last_exc = None
        for method, path, body in attempts:
            try:
                if method == "POST":
                    return self._post(path, body=body)
                else:
                    # Strip None values (name is filled by caller if needed)
                    clean = {"data": {k: v for k, v in body["data"].items()
                                       if v is not None}}
                    return self._put(path, body=clean)
            except S1APIError as e:
                last_exc = e
                # 404 / "not found" = wrong endpoint shape — try next.
                # Other 4xx with a meaningful detail = real refusal,
                # surface immediately so the user sees the reason.
                if e.status_code in (404,):
                    continue
                msg = (str(getattr(e, "detail", "")) or str(e)).lower()
                if "not found" in msg or "unknown" in msg \
                        or "unrecognized" in msg:
                    continue
                raise
        if last_exc:
            raise last_exc
        return {}

    def reorder_groups(self, site_id: str, group_ids: list[str]) -> dict:
        """PUT /groups/ranks — set the evaluation order of a site's groups.

        `group_ids` must be ordered best-rank-first (index 0 becomes rank 1)
        and must contain DYNAMIC groups only: the endpoint is documented as
        "make sure the IDs of the groups in this command are for Dynamic
        groups", and feeding it a static/pinned/Default group makes it fail.

        The body schema (`groups_PutRanksSchema`) is not published and the
        documented responses are 204/400/401/403 — a 500 means the payload
        upset the server rather than the validator. The sibling reorder
        endpoints in this API take `data: {ids: [...]}`, so try that shape
        too before giving up. A rejected PUT changes no state, so retrying
        with a second shape is safe.
        """
        ids = [str(g) for g in group_ids]
        last_exc: Optional[S1APIError] = None
        for key in ("groupIds", "ids"):
            try:
                return self._put("/groups/ranks", body={
                    "filter": {"siteIds": [site_id]},
                    "data": {key: ids}})
            except S1APIError as e:
                last_exc = e
        raise last_exc  # type: ignore[misc]

    # ── agent migration ────────────────────────────────────────────────

    def migrate_agent(self, agent_id: str, token: str) -> dict:
        return self._post("/agents/actions/move-to-console", body={
            "filter": {"ids": [agent_id]}, "data": {"token": token}})

    def move_agents_to_site(self, agent_ids: list[str], site_id: str) -> dict:
        return self._post("/agents/actions/move-to-site", body={
            "filter": {"ids": agent_ids}, "data": {"targetSiteId": site_id}})

    # ── HTTP DELETE ────────────────────────────────────────────────────

    def _delete(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        return self._request("DELETE", endpoint, params=params, body=body)

    # ── agent actions ──────────────────────────────────────────────────

    def get_agent_count(self, params: Optional[dict] = None) -> int:
        p = dict(params or {})
        p["countOnly"] = "true"
        body = self._get("/agents", p)
        return body.get("pagination", {}).get("totalItems", 0)

    def initiate_scan(self, agent_ids: list[str]) -> dict:
        return self._post("/agents/actions/initiate-scan", body={
            "filter": {"ids": agent_ids}, "data": {}})

    def abort_scan(self, agent_ids: list[str]) -> dict:
        return self._post("/agents/actions/abort-scan", body={
            "filter": {"ids": agent_ids}, "data": {}})

    def uninstall_agent(self, agent_ids: list[str]) -> dict:
        return self._post("/agents/actions/uninstall", body={
            "filter": {"ids": agent_ids}, "data": {}})

    def move_agents_to_group(self, agent_ids: list[str], group_id: str) -> dict:
        return self._post("/agents/actions/move-to-group", body={
            "filter": {"ids": agent_ids}, "data": {"targetGroupId": group_id}})

    def set_agent_customer_identifier(self, agent_ids: list[str], identifier: str) -> dict:
        return self._post("/agents/actions/set-external-id", body={
            "filter": {"ids": agent_ids}, "data": {"externalId": identifier}})

    def get_agent_passphrase(self, agent_id: str) -> list[dict]:
        return self.get_all("/agents/passphrases", params={"ids": agent_id})

    # ── threats ────────────────────────────────────────────────────────

    def get_threats(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/threats", params=params, **kw)

    def get_threat_timeline(self, threat_id: str) -> list[dict]:
        return self.get_all(f"/threats/{threat_id}/timeline")

    def get_threat_notes(self, threat_id: str) -> list[dict]:
        return self.get_all(f"/threats/{threat_id}/notes")

    def create_threat_note(self, threat_ids: list[str], text: str) -> dict:
        return self._post("/threats/notes", body={
            "filter": {"ids": threat_ids}, "data": {"text": text}})

    def delete_threat_note(self, threat_id: str, note_id: str) -> dict:
        return self._delete(f"/threats/{threat_id}/notes/{note_id}")

    # ── threat intel ───────────────────────────────────────────────────

    def get_threat_intel(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/threat-intelligence/iocs", params=params, **kw)

    def upsert_threat_intel(self, scope: dict, iocs: list[dict]) -> dict:
        return self._post("/threat-intelligence/iocs", body={
            "filter": scope, "data": iocs})

    def delete_threat_intel(self, scope: dict, uuids: list[str]) -> dict:
        return self._delete("/threat-intelligence/iocs", body={
            "filter": {**scope, "uuids": uuids}})

    # ── activities ─────────────────────────────────────────────────────

    def get_activity_types(self) -> list[dict]:
        return self._get("/activities/types").get("data", [])

    def get_activities(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/activities", params={
            "includeHidden": "true", **(params or {})}, **kw)

    # ── deep visibility ───────────────────────────────────────────────

    def dv_create_query(self, query: str, from_date: str, to_date: str) -> str:
        body = self._post("/dv/init-query", body={
            "query": query, "fromDate": from_date, "toDate": to_date})
        return body.get("data", {}).get("queryId", "")

    def dv_get_query_status(self, query_id: str) -> dict:
        return self._get("/dv/query-status", params={"queryId": query_id}).get("data", {})

    def dv_get_events(self, query_id: str, params: Optional[dict] = None, **kw) -> list[dict]:
        p = dict(params or {})
        p["queryId"] = query_id
        return self.get_all("/dv/events", params=p, **kw)

    # ── applications / CVEs ────────────────────────────────────────────

    def get_applications(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/installed-applications", params=params, **kw)

    def get_application_cves(self, app_id: str) -> list[dict]:
        return self.get_all("/installed-applications/cves", params={"applicationIds": app_id})

    # ── ranger / rogues ────────────────────────────────────────────────

    def get_ranger(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/ranger/table-view", params=params, **kw)

    def get_rogues(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/rogues/table-view", params=params, **kw)

    # ── users / roles ──────────────────────────────────────────────────

    def get_users(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/users", params=params, **kw)

    def create_user(self, data: dict) -> dict:
        return self._post("/users", body={"data": data})

    def enroll_2fa(self, user_ids: list[str]) -> dict:
        return self._post("/users/enroll-2fa", body={"data": {"ids": user_ids}})

    def get_roles(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/rbac/roles", params=params, **kw)

    def get_role(self, role_id: str, params: Optional[dict] = None) -> dict:
        return self.get_data(f"/rbac/role/{role_id}", params=params)

    def get_token_details(self, token: str) -> dict:
        return self._post("/users/api-token-details", body={
            "data": {"apiToken": token}})

    # ── remote scripts / tasks ─────────────────────────────────────────

    def get_scripts(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/remote-scripts", params=params, **kw)

    def create_script(self, data: dict) -> dict:
        # Note: the script *body* is stored in per-tenant cloud storage and is
        # not returned by GET /remote-scripts, so a create from a backup
        # payload only succeeds when the metadata carries a re-usable content
        # reference. Restore treats the library as inventory (see RestorePage).
        return self._post("/remote-scripts", body={"data": data})

    def remove_script(self, script_id: str) -> dict:
        return self._delete("/remote-scripts", body={
            "filter": {"ids": [script_id]}})

    def get_tasks(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/private/bulk-tasks", params={
            "sortBy": "createdAt", "sortOrder": "desc", **(params or {})}, **kw)

    # ── accounts CRUD ──────────────────────────────────────────────────

    def create_account(self, data: dict) -> dict:
        return self._post("/accounts", body={"data": data})

    def update_account(self, account_id: str, data: dict) -> dict:
        return self._put(f"/accounts/{account_id}", body={"data": data})

    # ── GraphQL core ──────────────────────────────────────────────────

    def _gql(self, path: str, query: str, variables: Optional[dict] = None) -> dict:
        body = {"query": query}
        if variables:
            body["variables"] = variables
        resp = self._post(path, body=body)
        if resp.get("errors"):
            first = resp["errors"][0].get("message", "GraphQL error")
            raise S1APIError(f"GraphQL: {first}", 0, str(resp["errors"]))
        return resp

    # ── Purple AI ─────────────────────────────────────────────────────

    PURPLE_VIEW_SELECTORS = ("EDR", "IDENTITY", "CLOUD", "NGFW", "DATA_LAKE")

    def purple_query(self, user_input: str, view_selector: str = "EDR",
                     hours: int = 24) -> dict:
        now_ms = int(_time.time() * 1000)
        end_ms = now_ms
        start_ms = now_ms - hours * 60 * 60 * 1000
        query = f"""query PurpleLaunch($input: String!) {{
  purpleLaunchQuery(request: {{
    isAsync: false
    contentType: NATURAL_LANGUAGE
    consoleDetails: {{ baseUrl: "{self.base_url}" version: "S" }}
    conversation: {{ id: "S1CC-SESSION", messages: [], entitlements: null }}
    inputContent: {{
      userInput: $input
      displayedTimeRange: {{ start: {start_ms}, end: {end_ms} }}
      viewSelector: {view_selector}
      contentType: NATURAL_LANGUAGE
      userDetails: {{
        accountId: ""
        teamToken: ""
        sessionId: "s1cc-session"
        emailAddress: null
        userAgent: "S1-Command-Center"
        buildDate: null
        buildHash: null
      }}
    }}
  }}) {{
    result {{
      message
      summary
      powerQuery {{ query timeRange {{ start end }} viewSelector }}
      suggestedQuestions {{ question }}
    }}
    resultType
    status {{ state error {{ errorDetail errorType origin }} }}
    stepsCompleted
    token
  }}
}}"""
        resp = self._gql("/graphql", query, {"input": user_input})
        plq = (resp.get("data") or {}).get("purpleLaunchQuery") or {}
        status = plq.get("status") or {}
        err = status.get("error")
        if err:
            raise S1APIError(
                f"Purple AI: {err.get('errorType', 'error')}: {err.get('errorDetail', '')}",
                0, str(err))
        result = plq.get("result") or {}
        pq = result.get("powerQuery") or {}
        tr = pq.get("timeRange") or {}
        suggestions = [q.get("question") for q in (result.get("suggestedQuestions") or [])
                       if q.get("question")]
        return {
            "state": status.get("state"),
            "result_type": plq.get("resultType"),
            "message": result.get("message") or "",
            "summary": result.get("summary"),
            "power_query": pq.get("query"),
            "view_selector": pq.get("viewSelector"),
            "time_range": {"start": tr.get("start"), "end": tr.get("end")} if tr else None,
            "suggested_questions": suggestions,
        }

    # ── Unified Alert Management (UAM) ────────────────────────────────

    UAM_GQL = "/unifiedalerts/graphql"

    _ALERT_FIELDS = (
        "id detectedAt createdAt updatedAt name status severity analystVerdict "
        "externalId storylineId attackSurfaces confidenceLevel classification "
        "detectionSource { product vendor } assignee { fullName email }"
    )

    _ALERT_DETAIL_FIELDS = _ALERT_FIELDS + (
        " assets { id name agentUuid category subcategory osType osVersion "
        "primary accessible decommissioned deleted status agentVersion "
        "lastLoggedInUser } "
        "dataSources { id name }"
    )

    def uam_list_alerts(self, filters: Optional[list] = None,
                        sort_by: str = "detectedAt", sort_order: str = "DESC",
                        first: int = 50, after: Optional[str] = None,
                        view_type: Optional[str] = None) -> dict:
        args = ["filters: $filters", "sort: {by: $sortBy, order: $sortOrder}",
                "first: $first"]
        var_defs = ["$filters: [FilterInput!]", "$sortBy: String!",
                    "$sortOrder: SortOrderType!", "$first: Int"]
        variables: dict = {"filters": filters or [], "sortBy": sort_by,
                           "sortOrder": sort_order, "first": first}
        if after:
            args.append("after: $after")
            var_defs.append("$after: String")
            variables["after"] = after
        if view_type:
            args.append("viewType: $viewType")
            var_defs.append("$viewType: ViewType")
            variables["viewType"] = view_type
        query = f"""query listAlerts({', '.join(var_defs)}) {{
  alerts({', '.join(args)}) {{
    edges {{ node {{ {self._ALERT_FIELDS} }} cursor }}
    pageInfo {{ hasNextPage endCursor }}
    totalCount
  }}
}}"""
        r = self._gql(self.UAM_GQL, query, variables)
        return (r.get("data") or {}).get("alerts") or {}

    def uam_get_alert(self, alert_id: str) -> dict:
        query = f"""query alertOne($id: ID!) {{
  alert(id: $id) {{ {self._ALERT_DETAIL_FIELDS} }}
}}"""
        r = self._gql(self.UAM_GQL, query, {"id": alert_id})
        return (r.get("data") or {}).get("alert") or {}

    def uam_facets(self, field_ids: list[str],
                   filters: Optional[list] = None) -> list[dict]:
        query = """query g($fieldIds: [String!]!, $filters: [FilterInput!]) {
  alertGroupByCount(fieldIds: $fieldIds, filters: $filters) {
    data { fieldId hasNextPage values { value label count } }
  }
}"""
        r = self._gql(self.UAM_GQL, query,
                      {"fieldIds": field_ids, "filters": filters or []})
        return ((r.get("data") or {}).get("alertGroupByCount") or {}).get("data") or []

    def uam_alert_notes(self, alert_id: str) -> list[dict]:
        query = """query n($id: ID!) {
  alertNotes(alertId: $id) {
    data { id alertId text createdAt type author { fullName email } }
  }
}"""
        r = self._gql(self.UAM_GQL, query, {"id": alert_id})
        return ((r.get("data") or {}).get("alertNotes") or {}).get("data") or []

    def uam_add_note(self, alert_id: str, text: str) -> list[dict]:
        query = """mutation add($id: ID!, $text: String!) {
  addAlertNote(alertId: $id, text: $text) {
    data { id alertId text createdAt author { fullName } }
  }
}"""
        r = self._gql(self.UAM_GQL, query, {"id": alert_id, "text": text})
        return ((r.get("data") or {}).get("addAlertNote") or {}).get("data") or []

    def uam_alert_history(self, alert_id: str, first: int = 50) -> dict:
        query = """query h($id: ID!, $first: Int) {
  alertHistory(alertId: $id, first: $first) {
    edges { node { createdAt eventType eventText } cursor }
    pageInfo { hasNextPage endCursor }
    totalCount
  }
}"""
        r = self._gql(self.UAM_GQL, query, {"id": alert_id, "first": first})
        return (r.get("data") or {}).get("alertHistory") or {}

    def uam_alert_timeline(self, alert_id: str, first: int = 50) -> dict:
        query = """query t($id: ID!, $first: Int) {
  alertTimeline(alertId: $id, first: $first) {
    edges { node { createdAt eventType eventText } cursor }
    pageInfo { hasNextPage endCursor }
    totalCount
  }
}"""
        r = self._gql(self.UAM_GQL, query, {"id": alert_id, "first": first})
        return (r.get("data") or {}).get("alertTimeline") or {}

    def uam_set_status(self, scope_ids: list[str], alert_ids: list[str],
                       status: str, note: Optional[str] = None) -> dict:
        actions = [{"id": "S1/alert/statusUpdate",
                    "payload": {"status": {"value": status}}}]
        if note:
            actions.append({"id": "S1/alert/addNote",
                            "payload": {"note": {"value": note}}})
        filt = {"or": [{"and": [{"fieldId": "id",
                                  "stringIn": {"values": alert_ids}}]}]}
        query = """mutation trigger($scope: ScopeSelectorInput!,
  $filter: OrFilterSelectionInput, $actions: [TriggerActionInput!]!,
  $viewType: ViewType!) {
  alertTriggerActions(scope: $scope, filter: $filter, actions: $actions,
    viewType: $viewType) {
    __typename
    ... on ActionsTriggered {
      actions { actionId success { id } skip { id } failure { id } }
    }
    ... on TriggerActionsError { errors { errorMessage } }
    ... on TriggerActionsScheduled { bulkActionTriggerId }
  }
}"""
        variables = {"scope": {"scopeIds": scope_ids, "scopeType": "ACCOUNT"},
                     "filter": filt, "actions": actions, "viewType": "ALL"}
        r = self._gql(self.UAM_GQL, query, variables)
        return (r.get("data") or {}).get("alertTriggerActions") or {}

    def uam_set_verdict(self, scope_ids: list[str], alert_ids: list[str],
                        verdict: str) -> dict:
        filt = {"or": [{"and": [{"fieldId": "id",
                                  "stringIn": {"values": alert_ids}}]}]}
        actions = [{"id": "S1/alert/analystVerdictUpdate",
                    "payload": {"analystVerdict": {"value": verdict}}}]
        query = """mutation trigger($scope: ScopeSelectorInput!,
  $filter: OrFilterSelectionInput, $actions: [TriggerActionInput!]!,
  $viewType: ViewType!) {
  alertTriggerActions(scope: $scope, filter: $filter, actions: $actions,
    viewType: $viewType) {
    __typename
    ... on ActionsTriggered {
      actions { actionId success { id } skip { id } failure { id } }
    }
    ... on TriggerActionsError { errors { errorMessage } }
  }
}"""
        variables = {"scope": {"scopeIds": scope_ids, "scopeType": "ACCOUNT"},
                     "filter": filt, "actions": actions, "viewType": "ALL"}
        r = self._gql(self.UAM_GQL, query, variables)
        return (r.get("data") or {}).get("alertTriggerActions") or {}

    def uam_export_csv(self, filters: Optional[list] = None,
                       view_type: str = "ALL") -> str:
        query = """query ($filters: [FilterInput!], $viewType: ViewType!) {
  alertsCsvExport(filters: $filters, viewType: $viewType) { data }
}"""
        r = self._gql(self.UAM_GQL, query,
                      {"filters": filters or [], "viewType": view_type})
        return ((r.get("data") or {}).get("alertsCsvExport") or {}).get("data") or ""
