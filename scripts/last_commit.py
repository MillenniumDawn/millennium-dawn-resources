#!/usr/bin/env python3
"""Find the last commit a user (or every member of a team) made in an org.

Combines two GitHub data sources to avoid the default-branch blind spot:

  * `search/commits`        — every commit on a repo's **default branch**,
                              lifetime data, no time window.
  * `users/{u}/events/orgs/{o}` — PushEvents on **any branch** in the org,
                              including feature branches, last ~90 days.

The two are merged per user and the more recent timestamp wins. Without the
events source, anyone whose work lives on unmerged feature branches looks
inactive (which is the symptom this script was originally hiding).

Usage:
    # one user
    ./last_commit.py --user AngriestBird

    # every member of a team, oldest activity first
    ./last_commit.py --team team-members

    # constrain to a single repo
    ./last_commit.py --user AngriestBird --repo MillenniumDawn/Millennium-Dawn

    # JSON
    ./last_commit.py --team team-members --json > activity.json

Auth: requires `gh auth login` with `read:org` (for --team) and `repo` (the
search/commits endpoint reads commit data; public repos work with the
default token). No PAT plumbing needed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any


def gh_api(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET a REST endpoint through the gh CLI and return the parsed body."""
    cmd = ["gh", "api", "-X", "GET", path]
    for key, value in params.items():
        if isinstance(value, bool):
            cmd += ["-F", f"{key}={'true' if value else 'false'}"]
        elif isinstance(value, int):
            cmd += ["-F", f"{key}={value}"]
        else:
            cmd += ["-f", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"gh api failed (exit {result.returncode}): {result.stderr.strip()}")
    return json.loads(result.stdout)


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            cmd += ["-F", f"{key}=null"]
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


def team_members(org: str, slug: str) -> list[str]:
    members: list[str] = []
    cursor: str | None = None
    while True:
        data = gh_graphql(TEAM_MEMBERS_QUERY, {"org": org, "slug": slug, "cursor": cursor})
        team = data["organization"]["team"]
        if team is None:
            sys.exit(f"Team '{slug}' not found in org '{org}' (or insufficient scopes).")
        page = team["members"]
        members.extend(node["login"] for node in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return sorted(members)
        cursor = page["pageInfo"]["endCursor"]


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    return text.splitlines()[0]


def last_default_branch_commit(
    user: str, *, org: str | None, repo: str | None
) -> dict[str, Any] | None:
    """Most recent commit by `user` indexed by search/commits.

    Important caveat: GitHub's search/commits endpoint only indexes commits
    on each repo's default branch. Feature-branch work is invisible here —
    see `last_push_event_in_org` for that.
    """
    if repo:
        query = f"repo:{repo} author:{user}"
    elif org:
        query = f"org:{org} author:{user}"
    else:
        query = f"author:{user}"

    body = gh_api(
        "search/commits",
        {"q": query, "sort": "committer-date", "order": "desc", "per_page": 1},
    )
    items = body.get("items") if isinstance(body, dict) else None
    if not items:
        return None
    item = items[0]
    commit = item.get("commit", {})
    return {
        "sha": item["sha"][:7],
        "full_sha": item["sha"],
        "date": (commit.get("committer") or {}).get("date", ""),
        "repo": (item.get("repository") or {}).get("full_name", ""),
        "branch": "(default)",
        "message": _first_line(commit.get("message")),
        "url": item.get("html_url", ""),
        "source": "search-commits",
    }


def last_push_event_in_org(user: str, org: str) -> dict[str, Any] | None:
    """Most recent PushEvent by `user` within `org` across any branch.

    Uses the public events feed (`/users/{u}/events/public`), which is
    capped at ~300 events / 90 days. Filters down to events whose repo
    belongs to `org`. Catches commits to feature branches that the
    search/commits API does not index. Returns None if the user has no
    qualifying PushEvent in the window.
    """
    body = gh_api(f"users/{user}/events/public", {"per_page": 100})
    if not isinstance(body, list):
        return None
    org_prefix = f"{org}/"
    for event in body:
        if event.get("type") != "PushEvent":
            continue
        repo_name = (event.get("repo") or {}).get("name") or ""
        if not repo_name.startswith(org_prefix):
            continue
        payload = event.get("payload") or {}
        ref = payload.get("ref") or ""
        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref
        commits = payload.get("commits") or []
        head_commit = commits[-1] if commits else {}
        # payload.head is the post-push tip; the commits[] array is empty on
        # force-pushes and over-size pushes, so prefer payload.head for SHA.
        sha = payload.get("head") or head_commit.get("sha") or ""
        return {
            "sha": sha[:7] if sha else "",
            "full_sha": sha,
            "date": event.get("created_at") or "",
            "repo": repo_name,
            "branch": branch,
            "message": _first_line(head_commit.get("message")),
            "url": f"https://github.com/{repo_name}/commit/{sha}" if sha and repo_name else "",
            "source": "push-event",
        }
    return None


def last_commit(user: str, *, org: str | None, repo: str | None) -> dict[str, Any] | None:
    """Combine the default-branch and PushEvent signals; return the newer one."""
    candidates: list[dict[str, Any]] = []
    if org and not repo:
        push = last_push_event_in_org(user, org)
        if push:
            candidates.append(push)
    commit = last_default_branch_commit(user, org=org, repo=repo)
    if commit:
        candidates.append(commit)
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["date"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--org",
        default=os.environ.get("MD_ORG", "MillenniumDawn"),
        help="GitHub organization to scope the search to (default: MillenniumDawn or $MD_ORG).",
    )
    parser.add_argument(
        "--repo",
        help="Limit search to a single repo (owner/name). Overrides --org scoping.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user", help="Look up the last commit for one GitHub login.")
    target.add_argument(
        "--team",
        help="Iterate over every member of this team (slug within --org).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON instead of text.",
    )
    args = parser.parse_args()

    users = [args.user] if args.user else team_members(args.org, args.team)

    rows: list[dict[str, Any]] = []
    for login in users:
        info = last_commit(login, org=args.org if not args.repo else None, repo=args.repo)
        rows.append({"user": login, "last_commit": info})

    # Sort: users with no commits first (most stale), then by date ascending.
    rows.sort(
        key=lambda r: (r["last_commit"] is not None, (r["last_commit"] or {}).get("date", ""))
    )

    if args.as_json:
        json.dump(
            {
                "org": args.org,
                "repo": args.repo,
                "scope": "user" if args.user else f"team:{args.team}",
                "results": rows,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    scope = f"repo {args.repo}" if args.repo else f"org {args.org}"
    if args.user:
        print(f"Last commit by {args.user} in {scope}:")
    else:
        print(f"Last commit per member of team '{args.team}' in {scope} (stalest first):\n")
        print(f"{'USER':<24} {'DATE':<20} {'BRANCH':<24} {'SHA':<8} " f"{'REPO':<36} MESSAGE")

    for row in rows:
        info = row["last_commit"]
        if info is None:
            if args.user:
                print("  (no commits found)")
            else:
                print(f"{row['user']:<24} {'(no commits)':<20} {'-':<24} {'-':<8} " f"{'-':<36} -")
            continue
        date = info["date"][:19].replace("T", " ")
        branch = info.get("branch") or "(default)"
        if args.user:
            print(f"  {date} UTC  {info['sha']}  {info['repo']}  [{branch}]  ({info['source']})")
            print(f"  {info['message']}")
            print(f"  {info['url']}")
        else:
            msg = info["message"]
            if len(msg) > 50:
                msg = msg[:47] + "..."
            if len(branch) > 23:
                branch = branch[:20] + "..."
            print(
                f"{row['user']:<24} {date:<20} {branch:<24} {info['sha']:<8} "
                f"{info['repo']:<36} {msg}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
