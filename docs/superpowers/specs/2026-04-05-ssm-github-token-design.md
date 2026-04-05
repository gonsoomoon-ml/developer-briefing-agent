# SSM Parameter Store for GitHub Token

**Date:** 2026-04-05
**Status:** Approved

## Problem

The agent has `shell` tool access and inherits `GITHUB_TOKEN` from `os.environ`. The LLM could autonomously run `env` or `cat .env`, exposing the token in tool output sent to Amazon Bedrock. In the AgentCore deploy path, the token is also visible in `--env` CLI arguments.

## Decision

Fetch the GitHub token inside `github_standup.py` via AWS SSM Parameter Store, so it never enters the agent's process environment. Fall back to `os.environ` for local/offline dev.

## Design

### Token resolution order

1. SSM Parameter Store: `/developer-briefing-agent/github-token` (SecureString, `WithDecryption=True`)
2. Fallback: `os.environ.get("GITHUB_TOKEN")`
3. If neither available: error and exit (existing behavior)

### SSM parameter setup (one-time)

```bash
aws ssm put-parameter \
  --name "/developer-briefing-agent/github-token" \
  --type SecureString \
  --value "ghp_xxx"
```

### Code change

Add `get_github_token()` to `github_standup.py`, replacing the direct `os.environ.get("GITHUB_TOKEN")` call:

```python
def get_github_token() -> str | None:
    try:
        import boto3
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(
            Name="/developer-briefing-agent/github-token",
            WithDecryption=True,
        )
        return resp["Parameter"]["Value"]
    except Exception:
        return os.environ.get("GITHUB_TOKEN")
```

### Files touched

- `skills/alex/scripts/github_standup.py` — add `get_github_token()`, replace token fetch
- `skills/maria/scripts/github_standup.py` — same change

### Files NOT touched

- `strands_agent.py` — no changes needed
- `agentcore_runtime.py` — no changes needed
- `pyproject.toml` — `boto3` already a dependency

## Security properties

- **SSM active:** Token exists only inside `github_standup.py` process memory and HTTPS headers to `api.github.com`. The agent's `os.environ` has no `GITHUB_TOKEN`. LLM running `env` sees nothing.
- **SSM unavailable (fallback):** Behaves exactly as today — token in env. No regression.
- **No new dependencies:** `boto3` is already in `pyproject.toml`.

## Trade-offs

- Adds ~200ms latency on first SSM call per script invocation (cached by boto3 within the process)
- Requires AWS credentials to be available (already needed for Bedrock)
- Fallback to env means local dev works without SSM setup
