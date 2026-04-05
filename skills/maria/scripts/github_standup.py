#!/usr/bin/env python3
"""GitHub standup data fetcher — CLI script for Strands AgentSkills.

Usage:
    python github_standup.py --repos owner/repo1 owner/repo2 --days 7
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

DEPENDABOT_ACCOUNTS = {"dependabot[bot]", "dependabot"}


def get(url: str, token: str) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Fetch GitHub activity for standup")
    parser.add_argument("--repos", nargs="+", required=True, help="Repos in owner/repo format")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print(json.dumps({"error": "GITHUB_TOKEN not set in environment"}))
        sys.exit(1)

    user = get("https://api.github.com/user", token)
    username = user.get("login", "")
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    result = {"username": username, "since": since[:10], "repos": {}}

    for repo in args.repos:
        commits_raw = get(
            f"https://api.github.com/repos/{repo}/commits"
            f"?author={username}&since={since}&per_page=10",
            token,
        )
        commits = (
            [
                {
                    "sha": c["sha"][:7],
                    "message": c["commit"]["message"].split("\n")[0][:100],
                    "date": c["commit"]["author"]["date"][:10],
                }
                for c in commits_raw
            ]
            if isinstance(commits_raw, list)
            else []
        )

        prs_raw = get(
            f"https://api.github.com/repos/{repo}/pulls"
            f"?state=open&per_page=5&sort=created&direction=desc",
            token,
        )
        open_prs = (
            [
                {
                    "number": p["number"],
                    "title": p["title"],
                    "author": p["user"]["login"],
                    "created_at": p["created_at"][:10],
                    "url": p["html_url"],
                }
                for p in prs_raw
                if p["user"]["login"] not in DEPENDABOT_ACCOUNTS
            ]
            if isinstance(prs_raw, list)
            else []
        )

        result["repos"][repo] = {"commits": commits, "open_prs": open_prs}

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
