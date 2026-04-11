#!/usr/bin/env python3
"""
github_standup.py — GitHub 활동 데이터 수집 CLI

Strands AgentSkills의 shell 툴에서 호출되어 GitHub API로 커밋, PR 데이터를 수집합니다.
토큰은 AWS SSM Parameter Store에서 먼저 조회하고, 실패 시 GITHUB_TOKEN 환경 변수로 폴백합니다.

사용법:
    python github_standup.py --repos owner/repo1 owner/repo2 --days 7
    python github_standup.py --repos owner/repo1 --days 7 --output /tmp/standup_data.json
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# SSM Parameter Store 경로
SSM_PARAM_NAME = "/developer-briefing-agent/github-token"


def get_github_token() -> str | None:
    """SSM Parameter Store에서 토큰을 조회하고, 실패 시 환경 변수로 폴백합니다."""
    try:
        import boto3
    except ImportError:
        return os.environ.get("GITHUB_TOKEN")
    try:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        return os.environ.get("GITHUB_TOKEN")


def get(url: str, token: str) -> dict | list:
    """GitHub REST API를 호출합니다."""
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
    parser = argparse.ArgumentParser(description="GitHub 활동 데이터 수집 (스탠드업용)")
    parser.add_argument("--repos", nargs="+", required=True, help="저장소 목록 (owner/repo 형식)")
    parser.add_argument("--days", type=int, default=7, help="조회 기간 (일, 기본값: 7)")
    parser.add_argument("--output", default=None, help="출력 파일 경로 (기본값: stdout)")
    args = parser.parse_args()

    # GitHub 토큰 조회 (SSM → 환경 변수 → 오류)
    token = get_github_token()
    if not token:
        print(json.dumps({"error": "GitHub 토큰을 찾을 수 없습니다 (SSM 및 GITHUB_TOKEN 환경 변수 확인)"}))
        sys.exit(1)

    # 현재 사용자 정보 조회
    user = get("https://api.github.com/user", token)
    username = user.get("login", "")
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    result = {"username": username, "since": since[:10], "repos": {}}

    for repo in args.repos:
        # 커밋 조회
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

        # 오픈 PR 조회 (봇 PR 포함 — SKILL.md에서 요약/그룹화 결정)
        prs_raw = get(
            f"https://api.github.com/repos/{repo}/pulls"
            f"?state=open&per_page=30&sort=created&direction=desc",
            token,
        )
        open_prs = (
            [
                {
                    "number": p["number"],
                    "title": p["title"],
                    "author": p["user"]["login"],
                    "is_bot": p["user"].get("type") == "Bot",
                    "created_at": p["created_at"][:10],
                    "url": p["html_url"],
                }
                for p in prs_raw
            ]
            if isinstance(prs_raw, list)
            else []
        )

        result["repos"][repo] = {"commits": commits, "open_prs": open_prs}

    # 결과 출력
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
