"""
Jira REST API client for the Home24 Localization Platform.

Credentials must be supplied via Streamlit secrets or environment variables:
  JIRA_BASE_URL    — e.g. https://your-company.atlassian.net
  JIRA_EMAIL       — your Atlassian account email
  JIRA_API_TOKEN   — API token from id.atlassian.com

Never hardcode credentials here.
"""

import os
import requests
from requests.auth import HTTPBasicAuth

# Fields requested from Jira for every issue search.
_ISSUE_FIELDS = "summary,status,assignee,created,updated,attachment,issuetype,priority"


def _load_jira_config() -> dict | None:
    """
    Return Jira credentials dict or None if not fully configured.
    Tries Streamlit secrets first, then environment variables.
    """
    base_url = email = api_token = ""

    try:
        import streamlit as st
        base_url  = st.secrets.get("JIRA_BASE_URL", "")
        email     = st.secrets.get("JIRA_EMAIL", "")
        api_token = st.secrets.get("JIRA_API_TOKEN", "")
    except Exception:
        pass

    base_url  = base_url  or os.environ.get("JIRA_BASE_URL", "")
    email     = email     or os.environ.get("JIRA_EMAIL", "")
    api_token = api_token or os.environ.get("JIRA_API_TOKEN", "")

    if not (base_url and email and api_token):
        return None

    return {
        "base_url":  base_url.rstrip("/"),
        "email":     email,
        "api_token": api_token,
    }


def jira_configured() -> bool:
    """Return True if all required Jira credentials are present."""
    return _load_jira_config() is not None


class JiraClient:
    """
    Thin wrapper around the Jira Cloud REST API v3.

    All public methods return structured dicts and never raise to callers.
    Timeouts are set on every request so the UI never hangs indefinitely.

    Search endpoint strategy (tried in order):
      1. GET /rest/api/3/search/jql  — newer cursor-based endpoint
      2. GET /rest/api/3/search      — classic start-at pagination, widely supported
    """

    _API = "/rest/api/3"

    def __init__(self) -> None:
        cfg = _load_jira_config()
        if not cfg:
            raise ValueError(
                "Jira credentials not configured. "
                "Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN in secrets or .env."
            )
        self._base    = cfg["base_url"]
        self._auth    = HTTPBasicAuth(cfg["email"], cfg["api_token"])
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base}{self._API}{path}"

    def _get(
        self,
        path: str,
        params: dict | None = None,
        timeout: int = 15,
    ) -> requests.Response:
        return self._session.get(self._url(path), params=params, timeout=timeout)

    def _post_json(
        self,
        path: str,
        body: dict,
        timeout: int = 20,
    ) -> requests.Response:
        return self._session.post(
            self._url(path),
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )

    @staticmethod
    def _parse_issues(data: dict) -> tuple[list[dict], int, str | None]:
        """
        Extract (issues_list, total, next_page_token) from any search response.
        Returns next_page_token=None when there are no more pages.
        """
        issues = []
        for item in data.get("issues", []):
            fields   = item.get("fields", {})
            raw_atts = fields.get("attachment") or []
            attachments = [
                {
                    "id":          att["id"],
                    "filename":    att["filename"],
                    "size":        att.get("size", 0),
                    "content_url": att["content"],
                    "mime_type":   att.get("mimeType", ""),
                    "created":     (att.get("created") or "")[:10],
                }
                for att in raw_atts
            ]
            issues.append({
                "key":              item["key"],
                "summary":          fields.get("summary") or "",
                "status":           (fields.get("status") or {}).get("name", ""),
                "assignee":         ((fields.get("assignee") or {}).get("displayName") or "Unassigned"),
                "created":          (fields.get("created") or "")[:10],
                "updated":          (fields.get("updated") or "")[:10],
                "attachment_count": len(attachments),
                "attachments":      attachments,
            })
        total           = data.get("total", len(issues))
        next_page_token = data.get("nextPageToken")  # present in /search/jql responses only
        return issues, total, next_page_token

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> dict:
        """
        Verify credentials by fetching the current user's profile.

        Returns {"ok": bool, "name": str, "email": str, "error": str}.
        """
        try:
            r = self._get("/myself", timeout=10)
            if r.status_code == 200:
                d = r.json()
                return {
                    "ok":    True,
                    "name":  d.get("displayName", ""),
                    "email": d.get("emailAddress", ""),
                    "error": "",
                }
            return {
                "ok": False, "name": "", "email": "",
                "error": f"HTTP {r.status_code}: {r.text[:200]}",
            }
        except Exception as exc:
            return {"ok": False, "name": "", "email": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Issue search  (robust multi-endpoint with fallback)
    # ------------------------------------------------------------------

    def search_issues(
        self,
        jql: str,
        max_results: int = 50,
        start_at: int = 0,
        next_page_token: str | None = None,
    ) -> dict:
        """
        Search Jira issues using JQL.

        Tries endpoints in order until one succeeds:
          1. GET /rest/api/3/search/jql  (cursor pagination via nextPageToken)
          2. GET /rest/api/3/search      (integer pagination via startAt)

        Returns {
            "issues":          list[dict],
            "total":           int,
            "next_page_token": str | None,   # for /search/jql cursor paging
            "start_at":        int,           # for /search integer paging
            "endpoint":        str,           # which endpoint succeeded
            "error":           str | None,
        }
        """
        errors: list[str] = []

        # ── Attempt 1: GET /rest/api/3/search/jql ────────────────────────────
        try:
            params: dict = {
                "jql":        jql,
                "maxResults": max_results,
                "fields":     _ISSUE_FIELDS,
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token

            r = self._get("/search/jql", params=params, timeout=20)
            if r.status_code == 200:
                issues, total, npt = self._parse_issues(r.json())
                return {
                    "issues":          issues,
                    "total":           total,
                    "next_page_token": npt,
                    "start_at":        start_at + len(issues),
                    "endpoint":        "/search/jql",
                    "error":           None,
                }
            if r.status_code not in (404, 405, 410):
                errors.append(f"/search/jql → HTTP {r.status_code}: {r.text[:300]}")
            else:
                errors.append(f"/search/jql → HTTP {r.status_code} (not supported)")
        except Exception as exc:
            errors.append(f"/search/jql → {exc}")

        # ── Attempt 2: GET /rest/api/3/search ────────────────────────────────
        try:
            r = self._get(
                "/search",
                params={
                    "jql":        jql,
                    "startAt":    start_at,
                    "maxResults": max_results,
                    "fields":     _ISSUE_FIELDS,
                },
                timeout=20,
            )
            if r.status_code == 200:
                issues, total, _ = self._parse_issues(r.json())
                return {
                    "issues":          issues,
                    "total":           total,
                    "next_page_token": None,
                    "start_at":        start_at + len(issues),
                    "endpoint":        "/search",
                    "error":           None,
                }
            errors.append(f"/search → HTTP {r.status_code}: {r.text[:300]}")
        except Exception as exc:
            errors.append(f"/search → {exc}")

        return {
            "issues":          [],
            "total":           0,
            "next_page_token": None,
            "start_at":        start_at,
            "endpoint":        "none",
            "error":           " | ".join(errors),
        }

    # ------------------------------------------------------------------
    # Saved filters
    # ------------------------------------------------------------------

    def search_filters(
        self,
        name_query: str,
        max_results: int = 20,
    ) -> list[dict]:
        """
        Search saved Jira filters by name.

        Returns list of {"id": str, "name": str, "jql": str}.
        """
        try:
            r = self._get(
                "/filter/search",
                params={
                    "filterName": name_query,
                    "maxResults":  max_results,
                    "expand":      "jql",
                },
                timeout=10,
            )
            if r.status_code == 200:
                data    = r.json()
                filters = data.get("values", data.get("results", []))
                return [
                    {
                        "id":   str(f.get("id", "")),
                        "name": f.get("name", ""),
                        "jql":  f.get("jql", ""),
                    }
                    for f in filters
                ]
            return []
        except Exception:
            return []

    def get_filter(self, filter_id: str) -> dict | None:
        """
        Fetch a saved filter by ID.

        Returns {"id": str, "name": str, "jql": str} or None on failure.
        """
        try:
            r = self._get(f"/filter/{filter_id}", timeout=10)
            if r.status_code == 200:
                f = r.json()
                return {
                    "id":   str(f.get("id", "")),
                    "name": f.get("name", ""),
                    "jql":  f.get("jql", ""),
                }
            return None
        except Exception:
            return None

    def search_issues_from_filter(
        self,
        filter_id: str,
        max_results: int = 50,
        start_at: int = 0,
    ) -> dict:
        """
        Fetch the JQL from a saved filter, then run search_issues().

        Returns the same dict as search_issues() plus "filter_name" and "filter_jql".
        """
        f = self.get_filter(filter_id)
        if not f:
            return {
                "issues": [], "total": 0, "next_page_token": None,
                "start_at": 0, "endpoint": "none",
                "error": f"Filter {filter_id} not found or inaccessible.",
                "filter_name": "", "filter_jql": "",
            }
        result = self.search_issues(f["jql"], max_results=max_results, start_at=start_at)
        result["filter_name"] = f["name"]
        result["filter_jql"]  = f["jql"]
        return result

    # ------------------------------------------------------------------
    # Attachment download
    # ------------------------------------------------------------------

    def download_attachment(self, content_url: str) -> bytes | None:
        """
        Download raw bytes from an attachment's content URL.
        Returns None on any failure.
        """
        try:
            r = self._session.get(content_url, timeout=60)
            return r.content if r.status_code == 200 else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Attachment upload
    # ------------------------------------------------------------------

    def upload_attachment(
        self,
        ticket_key: str,
        filename: str,
        file_bytes: bytes,
    ) -> dict:
        """
        Upload a file as an attachment to a Jira ticket.

        Uses multipart/form-data with X-Atlassian-Token: no-check as
        required by the Jira REST API. The field name must be "file".

        Returns {"ok": bool, "error": str}.
        """
        url = f"{self._base}{self._API}/issue/{ticket_key}/attachments"
        headers = {
            "X-Atlassian-Token": "no-check",
            "Accept":            "application/json",
        }
        try:
            r = requests.post(
                url,
                auth=self._auth,
                headers=headers,
                files={"file": (filename, file_bytes, "application/octet-stream")},
                timeout=90,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "error": ""}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def add_comment(self, ticket_key: str, text: str) -> dict:
        """
        Add a plain-text comment to a ticket.

        Jira Cloud API v3 requires Atlassian Document Format (ADF).
        Each non-empty line becomes a paragraph node.

        Returns {"ok": bool, "error": str}.
        """
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text]
        adf_content = [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ]
        try:
            r = self._post_json(
                f"/issue/{ticket_key}/comment",
                body={
                    "body": {
                        "type":    "doc",
                        "version": 1,
                        "content": adf_content,
                    }
                },
                timeout=15,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "error": ""}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def get_transitions(self, ticket_key: str) -> list[dict]:
        """
        Return available status transitions for a ticket.

        Returns list of {"id": str, "name": str}.
        """
        try:
            r = self._get(f"/issue/{ticket_key}/transitions", timeout=10)
            if r.status_code == 200:
                return [
                    {"id": t["id"], "name": t["name"]}
                    for t in r.json().get("transitions", [])
                ]
            return []
        except Exception:
            return []

    def apply_transition(self, ticket_key: str, transition_id: str) -> dict:
        """
        Apply a status transition to a ticket.

        Returns {"ok": bool, "error": str}.
        204 No Content is the success status code for this endpoint.
        """
        try:
            r = self._post_json(
                f"/issue/{ticket_key}/transitions",
                body={"transition": {"id": transition_id}},
                timeout=15,
            )
            if r.status_code == 204:
                return {"ok": True, "error": ""}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def get_jira_client() -> tuple[JiraClient | None, str]:
    """
    Try to instantiate a JiraClient.

    Returns (client, "") on success or (None, error_message) on failure.
    """
    try:
        cfg = _load_jira_config()
        if not cfg:
            return None, (
                "Jira credentials not configured. "
                "Add JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN "
                "to your Streamlit secrets or .env file."
            )
        return JiraClient(), ""
    except Exception as exc:
        return None, str(exc)
