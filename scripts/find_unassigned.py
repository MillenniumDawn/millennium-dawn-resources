#!/usr/bin/env python3
"""Find Millennium Dawn team members who have no GitHub project assignments.

Walks an org team's roster and the items on an organization ProjectV2 board,
then reports three things:
  1. Open project items (issues / PRs) with no assignee.
  2. Team members with zero project items assigned to them.
  3. Project assignees who are not on the team.

Authentication is handled by the `gh` CLI, so the operator just needs to be
logged in via `gh auth login` with `read:org` + `read:project` scopes. No
hand-managed PAT in env vars.

Usage:
    ./find_unassigned.py --org MillenniumDawn --team developers --project 1
    ./find_unassigned.py --json > report.json

Defaults can also come from MD_ORG / MD_TEAM / MD_PROJECT env vars.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Execute a GraphQL query through the gh CLI and return the `data` block."""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            cmd += ["-F", f"{key}=null"]
        elif isinstance(value, bool):
            cmd += ["-F", f"{key}={'true' if value else 'false'}"]
        elif isinstance(value, int):
            cmd += ["-F", f"{key}={value}"]
        else:
            cmd += ["-f", f"{key}={value}"]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"gh api failed (exit {result.returncode}): {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if payload.get("errors"):
        sys.exit(f"GraphQL errors: {json.dumps(payload['errors'], indent=2)}")
    return payload["data"]


TEAM_MEMBERS_QUERY = """
query($org: String!, $slug: String!, $cursor: String) {
  organization(login: $org) {
    team(slug: $slug) {
      members(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { login }
      }
    }
  }
}
"""


def team_members(org: str, slug: str) -> set[str]:
    members: set[str] = set()
    cursor: str | None = None
    while True:
        data = gh_graphql(TEAM_MEMBERS_QUERY, {"org": org, "slug": slug, "cursor": cursor})
        team = data["organization"]["team"]
        if team is None:
            sys.exit(f"Team '{slug}' not found in org '{org}' (or insufficient scopes).")
        page = team["members"]
        members.update(node["login"] for node in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return members
        cursor = page["pageInfo"]["endCursor"]


PROJECT_ITEMS_QUERY = """
query($org: String!, $num: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $num) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content {
            __typename
            ... on Issue {
              number
              state
              title
              url
              assignees(first: 20) { nodes { login } }
            }
            ... on PullRequest {
              number
              state
              title
              url
              assignees(first: 20) { nodes { login } }
            }
          }
        }
      }
    }
  }
}
"""


def project_items(org: str, project_number: int) -> tuple[list[dict[str, Any]], set[str]]:
    items: list[dict[str, Any]] = []
    assignees: set[str] = set()
    cursor: str | None = None
    while True:
        data = gh_graphql(
            PROJECT_ITEMS_QUERY,
            {"org": org, "num": project_number, "cursor": cursor},
        )
        project = data["organization"]["projectV2"]
        if project is None:
            sys.exit(
                f"Project #{project_number} not found in org '{org}' (or insufficient scopes)."
            )
        page = project["items"]
        for node in page["nodes"]:
            content = node.get("content") or {}
            if content.get("__typename") not in {"Issue", "PullRequest"}:
                continue
            logins = [a["login"] for a in content["assignees"]["nodes"]]
            items.append(
                {
                    "kind": content["__typename"],
                    "number": content["number"],
                    "state": content["state"],
                    "title": content.get("title", ""),
                    "url": content.get("url", ""),
                    "assignees": logins,
                }
            )
            assignees.update(logins)
        if not page["pageInfo"]["hasNextPage"]:
            return items, assignees
        cursor = page["pageInfo"]["endCursor"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--org",
        default=os.environ.get("MD_ORG", "MillenniumDawn"),
        help="GitHub organization login (default: MillenniumDawn or $MD_ORG)",
    )
    parser.add_argument(
        "--team",
        default=os.environ.get("MD_TEAM"),
        help="Team slug within the org (or $MD_TEAM). Required.",
    )
    parser.add_argument(
        "--project",
        type=int,
        default=int(os.environ["MD_PROJECT"]) if os.environ.get("MD_PROJECT") else None,
        help="Org ProjectV2 number (or $MD_PROJECT). Required.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of text.",
    )
    args = parser.parse_args()

    if not args.team:
        parser.error("--team is required (or set $MD_TEAM)")
    if args.project is None:
        parser.error("--project is required (or set $MD_PROJECT)")

    members = team_members(args.org, args.team)
    items, assigned = project_items(args.org, args.project)

    unassigned_open = [i for i in items if not i["assignees"] and i["state"] == "OPEN"]
    members_idle = sorted(members - assigned)
    outsiders = sorted(assigned - members)

    if args.as_json:
        json.dump(
            {
                "org": args.org,
                "team": args.team,
                "project": args.project,
                "team_size": len(members),
                "unassigned_open_items": unassigned_open,
                "team_members_with_no_items": members_idle,
                "non_team_assignees": outsiders,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    print(f"Team '{args.team}' in '{args.org}' has {len(members)} members.")
    print(f"\nOpen project items with no assignee: {len(unassigned_open)}")
    for item in unassigned_open:
        print(f"  #{item['number']:>5}  {item['title']}")

    print(f"\nTeam members with zero assigned items: {len(members_idle)}")
    for login in members_idle:
        print(f"  {login}")

    print(f"\nProject assignees not on the team: {len(outsiders)}")
    for login in outsiders:
        print(f"  {login}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
