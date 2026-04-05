# SSM GitHub Token Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch GitHub token from AWS SSM Parameter Store in `github_standup.py` so it never enters the agent's process environment.

**Architecture:** Add a `get_github_token()` function to `github_standup.py` that tries SSM first, falls back to `os.environ`. Apply the same change to both skill copies (alex, maria).

**Tech Stack:** boto3 (already in pyproject.toml), AWS SSM Parameter Store

---

### Task 1: Add `get_github_token()` to Alex's `github_standup.py`

**Files:**
- Modify: `skills/alex/scripts/github_standup.py:40-44`

- [ ] **Step 1: Add the `get_github_token` function**

Add this function before `main()` in `skills/alex/scripts/github_standup.py`:

```python
SSM_PARAM_NAME = "/developer-briefing-agent/github-token"


def get_github_token() -> str | None:
    """Fetch token from SSM Parameter Store, fall back to env var."""
    try:
        import boto3
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        return os.environ.get("GITHUB_TOKEN")
```

- [ ] **Step 2: Replace the token fetch in `main()`**

Change line 41 from:

```python
    token = os.environ.get("GITHUB_TOKEN")
```

to:

```python
    token = get_github_token()
```

- [ ] **Step 3: Verify the script still runs with env fallback**

Run:
```bash
cd /home/ubuntu/developer-briefing-agent && uv run python skills/alex/scripts/github_standup.py --repos gonsoomoon-ml/developer-briefing-agent --days 1 --output /tmp/test_alex.json
```

Expected: JSON file written to `/tmp/test_alex.json` with repo data (using env var fallback since SSM param may not exist yet).

- [ ] **Step 4: Commit**

```bash
git add skills/alex/scripts/github_standup.py
git commit -m "feat: fetch GitHub token from SSM Parameter Store in alex's script

Falls back to GITHUB_TOKEN env var when SSM is unavailable."
```

---

### Task 2: Apply same change to Maria's `github_standup.py`

**Files:**
- Modify: `skills/maria/scripts/github_standup.py:40-44`

- [ ] **Step 1: Add the `get_github_token` function**

Add this function before `main()` in `skills/maria/scripts/github_standup.py`:

```python
SSM_PARAM_NAME = "/developer-briefing-agent/github-token"


def get_github_token() -> str | None:
    """Fetch token from SSM Parameter Store, fall back to env var."""
    try:
        import boto3
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        return os.environ.get("GITHUB_TOKEN")
```

- [ ] **Step 2: Replace the token fetch in `main()`**

Change line 41 from:

```python
    token = os.environ.get("GITHUB_TOKEN")
```

to:

```python
    token = get_github_token()
```

- [ ] **Step 3: Verify the script still runs with env fallback**

Run:
```bash
cd /home/ubuntu/developer-briefing-agent && uv run python skills/maria/scripts/github_standup.py --repos gonsoomoon-ml/developer-briefing-agent --days 1 --output /tmp/test_maria.json
```

Expected: JSON file written to `/tmp/test_maria.json` with repo data.

- [ ] **Step 4: Commit**

```bash
git add skills/maria/scripts/github_standup.py
git commit -m "feat: fetch GitHub token from SSM Parameter Store in maria's script

Falls back to GITHUB_TOKEN env var when SSM is unavailable."
```

---

### Task 3: End-to-end verification with the agent

- [ ] **Step 1: Run the full agent to confirm nothing broke**

```bash
cd /home/ubuntu/developer-briefing-agent && uv run src/strands_agent.py
```

Expected: Agent produces a standup briefing as before, using env fallback.

- [ ] **Step 2 (optional, if SSM is set up): Store the token in SSM and remove from `.env`**

```bash
aws ssm put-parameter \
  --name "/developer-briefing-agent/github-token" \
  --type SecureString \
  --value "ghp_your_token"
```

Then remove `GITHUB_TOKEN` from `.env` and re-run the agent. The script should fetch from SSM and the agent's `env` output should show no `GITHUB_TOKEN`.
