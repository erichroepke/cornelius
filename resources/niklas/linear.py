"""Minimal Linear GraphQL helpers for Niklas MCP tools."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


LINEAR_ENDPOINT = "https://api.linear.app/graphql"


class LinearClient:
    def __init__(self, token: str | None = None, endpoint: str = LINEAR_ENDPOINT) -> None:
        self.token = token or os.environ.get("LINEAR_ACCESS_TOKEN", "")
        self.endpoint = endpoint
        if not self.token:
            raise RuntimeError("LINEAR_ACCESS_TOKEN is not configured")

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._authorization_header(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Linear API HTTP {exc.code}: {body}") from exc
        if data.get("errors"):
            messages = "; ".join(error.get("message", "unknown error") for error in data["errors"])
            raise RuntimeError(f"Linear GraphQL error: {messages}")
        return data.get("data", {})

    def _authorization_header(self) -> str:
        if self.token.lower().startswith("bearer "):
            return self.token
        prefix = os.environ.get("LINEAR_AUTH_PREFIX", "")
        return f"{prefix}{self.token}"

    def search_issues(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        data = self.graphql(
            """
            query NiklasSearchIssues($query: String!, $first: Int!) {
              issues(
                first: $first
                filter: {
                  or: [
                    { title: { contains: $query } }
                    { description: { contains: $query } }
                  ]
                }
              ) {
                nodes {
                  id
                  identifier
                  title
                  url
                  updatedAt
                  state { id name }
                  team { id key name }
                }
              }
            }
            """,
            {"query": query, "first": int(limit)},
        )
        return data.get("issues", {}).get("nodes", [])

    def create_issue(
        self,
        *,
        team_id: str,
        title: str,
        description: str | None = None,
        project_id: str | None = None,
        state_id: str | None = None,
    ) -> dict[str, Any]:
        input_data = {
            "teamId": team_id,
            "title": title,
            "description": description,
            "projectId": project_id,
            "stateId": state_id,
        }
        input_data = {key: value for key, value in input_data.items() if value is not None}
        data = self.graphql(
            """
            mutation NiklasCreateIssue($input: IssueCreateInput!) {
              issueCreate(input: $input) {
                success
                issue {
                  id
                  identifier
                  title
                  url
                  state { id name }
                  team { id key name }
                }
              }
            }
            """,
            {"input": input_data},
        )
        return data.get("issueCreate", {})

    def update_issue(self, issue_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        clean_input = {key: value for key, value in input_data.items() if value is not None}
        data = self.graphql(
            """
            mutation NiklasUpdateIssue($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                success
                issue {
                  id
                  identifier
                  title
                  url
                  state { id name }
                  team { id key name }
                }
              }
            }
            """,
            {"id": issue_id, "input": clean_input},
        )
        return data.get("issueUpdate", {})
