"""Relay — native GitHub, Linear, and ship integrations."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from creation.account.store import AccountStore
from creation.config import UserSecrets
from creation.services.pulse.notify import PulseNotify
from creation.services.types import OpsResult

logger = logging.getLogger(__name__)

TOOLKITS = ["github", "linear", "notify"]


class RelayOps:
    """First-party ship stack — GitHub REST + Linear GraphQL + Pulse notifications."""

    def __init__(self, secrets: UserSecrets, demo: bool = False):
        self.secrets = secrets
        self.demo = demo or not self._has_relay_credentials()
        self._pulse = PulseNotify(secrets)
        self._github_login = ""

    def _has_relay_credentials(self) -> bool:
        return bool(self.secrets.github_token.strip() or self.secrets.linear_api_key.strip())

    def _account(self):
        if self.secrets.account_token:
            user = AccountStore().get_by_api_key(self.secrets.account_token)
            if user:
                return user
        return AccountStore().ensure_local_account()

    @property
    def github_token(self) -> str:
        acct = self._account()
        return self.secrets.github_token.strip() or acct.github_token

    @property
    def linear_api_key(self) -> str:
        acct = self._account()
        return self.secrets.linear_api_key.strip() or acct.linear_api_key

    def _gh_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _linear_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.demo:
            return {"data": {"demo": True}}
        resp = httpx.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": self.linear_api_key, "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=30.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(str(payload["errors"]))
        return payload

    def run_action(self, slug: str, arguments: Dict[str, Any]) -> OpsResult:
        if self.demo:
            return OpsResult(True, f"[demo] {slug}", {"demo": True, "arguments": arguments})

        try:
            if slug == "LINEAR_GET_ALL_LINEAR_TEAMS":
                data = self._linear_query("{ teams { nodes { id name } } }")
                teams = data.get("data", {}).get("teams", {}).get("nodes", [])
                return OpsResult(True, slug, {"teams": teams})

            if slug == "LINEAR_CREATE_LINEAR_PROJECT":
                team_ids = arguments.get("team_ids") or [arguments.get("team_id")]
                q = """
                mutation($input: ProjectCreateInput!) {
                  projectCreate(input: $input) { project { id name url } }
                }
                """
                variables = {
                    "input": {
                        "name": arguments.get("name", "Creation build"),
                        "teamIds": [t for t in team_ids if t],
                        "description": arguments.get("description", ""),
                    }
                }
                data = self._linear_query(q, variables)
                project = data.get("data", {}).get("projectCreate", {}).get("project", {})
                merged = {"project": project, **project}
                return OpsResult(True, slug, merged)

            if slug == "LINEAR_GET_LINEAR_PROJECT":
                q = """
                query($id: String!) { project(id: $id) { id name url } }
                """
                data = self._linear_query(q, {"id": arguments["project_id"]})
                project = data.get("data", {}).get("project", {})
                return OpsResult(True, slug, {"project": project, **project})

            if slug == "LINEAR_CREATE_LINEAR_ISSUE":
                q = """
                mutation($input: IssueCreateInput!) {
                  issueCreate(input: $input) { issue { id identifier title url } }
                }
                """
                inp: Dict[str, Any] = {
                    "teamId": arguments.get("team_id"),
                    "title": arguments.get("title", "Task"),
                    "description": arguments.get("description", ""),
                }
                if arguments.get("project_id"):
                    inp["projectId"] = arguments["project_id"]
                data = self._linear_query(q, {"input": inp})
                issue = data.get("data", {}).get("issueCreate", {}).get("issue", {})
                return OpsResult(True, slug, {"issue": issue, **issue})

            if slug == "LINEAR_LIST_LINEAR_ISSUES":
                q = """
                query($filter: IssueFilter) {
                  issues(filter: $filter, first: 50) {
                    nodes { id identifier title state { name } }
                  }
                }
                """
                filt: Dict[str, Any] = {}
                if arguments.get("project_id"):
                    filt["project"] = {"id": {"eq": arguments["project_id"]}}
                data = self._linear_query(q, {"filter": filt})
                nodes = data.get("data", {}).get("issues", {}).get("nodes", [])
                return OpsResult(True, slug, {"issues": nodes, "nodes": nodes})

            if slug == "LINEAR_LIST_LINEAR_STATES":
                q = """
                query($id: String!) { team(id: $id) { states { nodes { id name } } } }
                """
                data = self._linear_query(q, {"id": arguments["team_id"]})
                nodes = data.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])
                return OpsResult(True, slug, {"states": nodes, "nodes": nodes})

            if slug == "LINEAR_UPDATE_ISSUE":
                q = """
                mutation($id: String!, $input: IssueUpdateInput!) {
                  issueUpdate(id: $id, input: $input) { issue { id } }
                }
                """
                inp = {}
                if arguments.get("state_id"):
                    inp["stateId"] = arguments["state_id"]
                data = self._linear_query(q, {"id": arguments["issue_id"], "input": inp})
                return OpsResult(True, slug, data.get("data", {}))

            if slug == "LINEAR_CREATE_PROJECT_UPDATE":
                q = """
                mutation($input: ProjectUpdateCreateInput!) {
                  projectUpdateCreate(input: $input) { projectUpdate { id body } }
                }
                """
                variables = {
                    "input": {
                        "projectId": arguments.get("project_id"),
                        "body": arguments.get("body", ""),
                    }
                }
                data = self._linear_query(q, variables)
                return OpsResult(True, slug, data.get("data", {}))

            if slug == "GITHUB_GET_THE_AUTHENTICATED_USER":
                resp = httpx.get("https://api.github.com/user", headers=self._gh_headers(), timeout=20.0)
                resp.raise_for_status()
                return OpsResult(True, slug, resp.json())

            if slug == "GITHUB_GET_A_REPOSITORY":
                owner, repo = arguments["owner"], arguments["repo"]
                resp = httpx.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=self._gh_headers(),
                    timeout=20.0,
                )
                if resp.status_code == 404:
                    return OpsResult(False, "repo not found")
                resp.raise_for_status()
                return OpsResult(True, slug, resp.json())

            if slug == "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER":
                resp = httpx.post(
                    "https://api.github.com/user/repos",
                    headers=self._gh_headers(),
                    json={
                        "name": arguments["name"],
                        "description": arguments.get("description", "")[:350],
                        "private": arguments.get("private", True),
                        "auto_init": arguments.get("auto_init", True),
                        "has_issues": True,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                return OpsResult(True, slug, resp.json())

            if slug == "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS":
                owner, repo, path = arguments["owner"], arguments["repo"], arguments["path"]
                content = arguments.get("content", "")
                message = arguments.get("message", "update")
                encoded = base64.b64encode(content.encode()).decode()
                get_resp = httpx.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                    headers=self._gh_headers(),
                    timeout=20.0,
                )
                sha = None
                if get_resp.status_code == 200:
                    sha = get_resp.json().get("sha")
                payload: Dict[str, Any] = {"message": message, "content": encoded}
                if sha:
                    payload["sha"] = sha
                put = httpx.put(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                    headers=self._gh_headers(),
                    json=payload,
                    timeout=30.0,
                )
                put.raise_for_status()
                return OpsResult(True, slug, put.json())

            return OpsResult(False, f"Unsupported relay action: {slug}")
        except Exception as exc:
            logger.warning("Relay %s failed: %s", slug, exc)
            return OpsResult(False, str(exc))

    def gather_context(self) -> List[str]:
        if self.demo:
            return [f"## {slug.title()}\nConnected — demo mode" for slug in TOOLKITS]
        blocks: List[str] = []
        if self.github_token:
            blocks.append("## GitHub\nConnected via Creation Relay.")
        else:
            blocks.append("## GitHub\nNot connected — add token in Account settings.")
        if self.linear_api_key:
            blocks.append("## Linear\nConnected via Creation Relay.")
        else:
            blocks.append("## Linear\nNot connected — add API key in Account settings.")
        blocks.append("## Notify\nPulse notifications ready.")
        return blocks

    def resolve_linear_team_id(self) -> str:
        if self.secrets.linear_team_id.strip():
            return self.secrets.linear_team_id.strip()
        acct = self._account()
        if acct.linear_team_id:
            return acct.linear_team_id
        if self.demo:
            return "demo-team-id"
        result = self.run_action("LINEAR_GET_ALL_LINEAR_TEAMS", {})
        teams = result.data.get("teams") or []
        if teams and isinstance(teams[0], dict):
            return str(teams[0].get("id") or "")
        return ""

    def resolve_github_owner(self) -> str:
        if self.demo:
            return ""
        result = self.run_action("GITHUB_GET_THE_AUTHENTICATED_USER", {})
        if not result.success:
            return ""
        return str(result.data.get("login") or "")

    def get_github_repo(self, owner: str, repo: str) -> OpsResult:
        if self.demo or not owner or not repo:
            return OpsResult(False, "[demo] no existing repo lookup")
        return self.run_action("GITHUB_GET_A_REPOSITORY", {"owner": owner, "repo": repo})

    def create_github_repo(self, name: str, description: str = "", private: bool = True) -> OpsResult:
        if self.demo:
            return OpsResult(
                True,
                "[demo] repo created",
                {"full_name": f"you/{name}", "html_url": f"https://github.com/you/{name}"},
            )
        return self.run_action(
            "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER",
            {"name": name, "description": description, "private": private, "auto_init": True},
        )

    def firecrawl_scrape(self, url: str) -> OpsResult:
        from creation.services.lens.search import LensScrape

        bundle = LensScrape(self.secrets, demo=self.demo).scrape_urls([url], max_pages=1)
        if bundle.hits:
            hit = bundle.hits[0]
            return OpsResult(True, "lens_scrape", {"markdown": hit.content, "url": hit.url, "title": hit.title})
        return OpsResult(False, f"Could not scrape {url}")

    def send_gmail(self, subject: str, body: str, to: str = "me") -> OpsResult:
        recipient = to if to and to != "me" else self.secrets.notify_email or self._account().notify_email
        return self._pulse.send(subject, body, recipient or "local@creation.dev")

    def create_linear_issue(self, title: str, description: str, team_id: str = "", project_id: str = "") -> OpsResult:
        args: Dict[str, Any] = {"team_id": team_id, "title": title, "description": description}
        if project_id:
            args["project_id"] = project_id
        if self.demo:
            return OpsResult(True, f"[demo] Linear: {title}")
        return self.run_action("LINEAR_CREATE_LINEAR_ISSUE", args)

    def github_upsert_file(self, owner: str, repo: str, path: str, content: str, message: str) -> OpsResult:
        if self.demo:
            return OpsResult(True, f"[demo] GitHub {owner}/{repo}:{path}")
        return self.run_action(
            "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS",
            {"owner": owner, "repo": repo, "path": path, "content": content, "message": message},
        )

    def github_create_file(self, path: str, content: str, message: str) -> OpsResult:
        return self.github_upsert_file(self.secrets.github_owner, self.secrets.github_repo, path, content, message)


# Back-compat alias — orchestrator and tests import ComposioOps
ComposioOps = RelayOps
