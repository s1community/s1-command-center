"""
SentinelOne API Client — handles auth, pagination, backup/restore data retrieval.
"""
import requests
from typing import Any, Optional


class S1APIError(Exception):
    def __init__(self, message: str, status_code: int = 0, detail: str = ""):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)


class S1API:
    API_PREFIX = "/web/api/v2.1"

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"ApiToken {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{self.API_PREFIX}"

    # ── HTTP primitives ────────────────────────────────────────────────

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        import time as _time
        last_exc = None
        for attempt in range(4):  # up to 4 attempts (0, 1, 2, 3)
            try:
                if attempt > 0:
                    _time.sleep(1.5 * attempt)  # 1.5s, 3s, 4.5s backoff
                resp = self.session.get(f"{self.api_url}{endpoint}", params=params, timeout=120)
                if resp.status_code != 200:
                    detail = ""
                    try:
                        detail = resp.json().get("errors", [{}])[0].get("detail", resp.text)
                    except Exception:
                        detail = resp.text
                    err = S1APIError(f"GET {endpoint} → {resp.status_code}", resp.status_code, detail)
                    # Don't retry client errors (400, 401, 403, 404, 405)
                    if 400 <= resp.status_code < 500:
                        raise err
                    raise err
                return resp.json()
            except S1APIError:
                raise  # don't retry API errors
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                    ConnectionResetError, ConnectionAbortedError) as e:
                last_exc = e
                if attempt < 3:
                    continue
        raise S1APIError(f"GET {endpoint} failed after 4 attempts: {last_exc}", 0, str(last_exc))

    def _post(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        resp = self.session.post(f"{self.api_url}{endpoint}", json=body, params=params, timeout=120)
        if resp.status_code not in (200, 201):
            detail = ""
            try:
                detail = resp.json().get("errors", [{}])[0].get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise S1APIError(f"POST {endpoint} → {resp.status_code}", resp.status_code, detail)
        return resp.json()

    def _put(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        resp = self.session.put(f"{self.api_url}{endpoint}", json=body, params=params, timeout=120)
        if resp.status_code not in (200, 201):
            detail = ""
            try:
                detail = resp.json().get("errors", [{}])[0].get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise S1APIError(f"PUT {endpoint} → {resp.status_code}", resp.status_code, detail)
        return resp.json()

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

    # ── quick helpers ──────────────────────────────────────────────────

    def get_my_user(self) -> dict:
        return self.get_data("/private/my-user")

    def get_accounts(self, **kw) -> list[dict]:
        return self.get_all("/accounts", params={"states": "active", "sortBy": "name", "sortOrder": "asc"}, **kw)

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

    # ── config overrides ───────────────────────────────────────────────

    def get_config_overrides(self, scope: dict) -> list[dict]:
        return self.get_all("/config-overrides", params=scope)

    def create_config_override(self, data: dict) -> dict:
        return self._post("/config-overrides", body={"data": data})

    def delete_config_overrides(self, ids: list[str]) -> dict:
        return self._delete("/config-overrides", body={
            "filter": {"ids": ids}})

    # ── locations ──────────────────────────────────────────────────────

    def create_location(self, scope: dict, data: dict) -> dict:
        return self._post("/locations", body={"filter": scope, "data": data})

    def delete_locations(self, ids: list[str]) -> dict:
        return self._delete("/locations", body={"filter": {"ids": ids}})

    # ── notification / integration settings ────────────────────────────

    def get_notification_settings(self, scope: dict) -> dict:
        return self.get_data("/settings/notifications", params=scope)

    def set_notification_settings(self, scope: dict, data: dict) -> dict:
        return self._put("/settings/notifications", body={
            "filter": scope, "data": data})

    def get_notification_recipients(self, scope: dict) -> list[dict]:
        return self.get_all("/settings/recipients", params=scope)

    def set_notification_recipients(self, scope: dict, data: list[dict]) -> dict:
        return self._put("/settings/recipients", body={
            "filter": scope, "data": {"emails": data}})

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

    def create_role(self, data: dict) -> dict:
        return self._post("/rbac/role", body={"data": data})

    def get_role_template(self) -> dict:
        return self.get_data("/rbac/role/template")

    # ── service users ──────────────────────────────────────────────────

    def get_service_users(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/service-users", params=params, **kw)

    def create_service_user(self, data: dict) -> dict:
        return self._post("/service-users", body={"data": data})

    # ── log collection rules ───────────────────────────────────────────

    def get_log_collection_rules(self, scope: dict) -> list[dict]:
        return self.get_all("/log-collection-rules", params=scope)

    def create_log_collection_rule(self, data: dict) -> dict:
        return self._post("/log-collection-rules", body={"data": data})

    # ── upgrade / auto-upgrade policies ────────────────────────────────

    def get_auto_upgrade_policies(self, scope: dict) -> list[dict]:
        return self.get_all("/agents-policy/auto-upgrade-policies", params=scope)

    def create_auto_upgrade_policy(self, data: dict) -> dict:
        return self._post("/agents-policy/auto-upgrade-policies", body={"data": data})

    # ── endpoint tags (unified) ────────────────────────────────────────

    def get_endpoint_tags(self, scope: dict) -> list[dict]:
        return self.get_all("/endpoint-tags", params=scope)

    def create_endpoint_tag(self, data: dict) -> dict:
        return self._post("/endpoint-tags", body={"data": data})

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

    # ── create site / group ──────────────────────────────────────────────

    def create_site(self, account_id: str, data: dict) -> dict:
        body = {"data": dict(data)}
        body["data"]["accountId"] = account_id
        return self._post("/sites", body=body)

    def create_group(self, site_id: str, data: dict) -> dict:
        body = {"data": dict(data)}
        body["data"]["siteId"] = site_id
        return self._post("/groups", body=body)

    def reorder_groups(self, site_id: str, group_ids: list[str]) -> dict:
        return self._put("/groups/ranks", body={
            "filter": {"siteIds": [site_id]},
            "data": {"groupIds": group_ids}})

    # ── agent migration ────────────────────────────────────────────────

    def migrate_agent(self, agent_id: str, token: str) -> dict:
        return self._post("/agents/actions/move-to-console", body={
            "filter": {"ids": [agent_id]}, "data": {"token": token}})

    def move_agents_to_site(self, agent_ids: list[str], site_id: str) -> dict:
        return self._post("/agents/actions/move-to-site", body={
            "filter": {"ids": agent_ids}, "data": {"targetSiteId": site_id}})

    # ── HTTP DELETE ────────────────────────────────────────────────────

    def _delete(self, endpoint: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        resp = self.session.delete(f"{self.api_url}{endpoint}", json=body, params=params, timeout=120)
        if resp.status_code not in (200, 201):
            detail = ""
            try:
                detail = resp.json().get("errors", [{}])[0].get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise S1APIError(f"DELETE {endpoint} → {resp.status_code}", resp.status_code, detail)
        return resp.json()

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

    def get_roles(self) -> list[dict]:
        return self.get_all("/rbac/roles")

    def get_token_details(self, token: str) -> dict:
        return self._post("/users/api-token-details", body={
            "data": {"apiToken": token}})

    # ── remote scripts / tasks ─────────────────────────────────────────

    def get_scripts(self, params: Optional[dict] = None, **kw) -> list[dict]:
        return self.get_all("/remote-scripts", params=params, **kw)

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
