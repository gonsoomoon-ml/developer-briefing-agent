# Architecture: Token Flow When Agent Calls a Skill

## Overview

When the agent runs, it loads a developer's `SKILL.md` via the `AgentSkills` plugin, then autonomously chains tool calls to collect GitHub data and generate a standup. The GitHub token is fetched inside the data-collection script — never in the agent's process environment.

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  User: uv run src/strands_agent.py                                  │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  strands_agent.py                                                    │
│                                                                      │
│  load_dotenv()  ← .env (DEV_NAME=sejong, STRANDS_NON_INTERACTIVE)     │
│                    ⚠ GITHUB_TOKEN is NOT needed here                 │
│                                                                      │
│  Agent(                                                              │
│    model = BedrockModel("global.anthropic.claude-sonnet-4-6")        │
│    tools = [shell, file_read]                                        │
│    plugins = [AgentSkills(skills="./skills/sejong/")]                   │
│  )                                                                   │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
          ┌────────────┼─── Agent autonomously decides tool calls ──┐
          │            │                                            │
          ▼            ▼                                            ▼
   ┌─────────┐  ┌───────────┐                              ┌────────────┐
   │ skills  │  │   shell   │                              │ file_read  │
   │ (step1) │  │  (step2)  │                              │  (step3)   │
   └────┬────┘  └─────┬─────┘                              └─────┬──────┘
        │             │                                          │
        ▼             ▼                                          ▼
┌──────────────┐  ┌──────────────────────────────────┐  ┌───────────────────┐
│  SKILL.md    │  │  github_standup.py               │  │ /tmp/standup_data │
│              │  │                                  │  │     .json         │
│ - format     │  │  get_github_token()              │  │                   │
│ - repos      │  │    │                             │  │ { commits, PRs }  │
│ - script cmd │  │    ├─ 1. Try SSM ──────────┐    │  └───────────────────┘
└──────────────┘  │    │                       │    │
                  │    │                       ▼    │
                  │    │  ┌─────────────────────┐   │
                  │    │  │ AWS SSM Parameter   │   │
                  │    │  │ Store (SecureString) │   │
                  │    │  │                     │   │
                  │    │  │ /developer-briefing │   │
                  │    │  │ -agent/github-token │   │
                  │    │  └──────────┬──────────┘   │
                  │    │             │              │
                  │    │     success │ failure      │
                  │    │         ┌───┘    │         │
                  │    │         │        ▼         │
                  │    │         │  2. Fallback:    │
                  │    │         │  os.environ      │
                  │    │         │  ["GITHUB_TOKEN"]│
                  │    │         │  (from .env)     │
                  │    │         │        │         │
                  │    │         ▼        ▼         │
                  │    │      token resolved        │
                  │    │         │                  │
                  │    │         ▼                  │
                  │    │  ┌─────────────────┐       │
                  │    │  │ GitHub REST API │       │
                  │    │  │ api.github.com  │       │
                  │    │  │                 │       │
                  │    │  │ • /user         │       │
                  │    │  │ • /repos/commits│       │
                  │    │  │ • /repos/pulls  │       │
                  │    │  └────────┬────────┘       │
                  │    │           │                │
                  │    │           ▼                │
                  │    │  → /tmp/standup_data.json  │
                  │    │                            │
                  └────┼────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LLM generates standup using:                                        │
│    • SKILL.md format rules (3 bullets / numbered list)               │
│    • JSON data (commits, PRs, open reviews)                          │
│                                                                      │
│  ✅ GITHUB_TOKEN never in agent's os.environ (when SSM active)       │
│  ✅ LLM running `env` sees nothing sensitive                         │
└──────────────────────────────────────────────────────────────────────┘
```

## Security Boundary

The key security property: `github_standup.py` runs as a **child process** via the `shell` tool. The token is fetched and used entirely within that process. It never flows back to the agent's environment where the LLM has introspection access.

| Path | Token in agent env? | Token visible to LLM? |
|------|--------------------|-----------------------|
| SSM active | No | No |
| SSM unavailable, `.env` fallback | Yes | Possible (via `env` command) |

## Token Resolution Order

```
get_github_token()
  │
  ├─ try: import boto3
  │   └─ ImportError → fall back to os.environ
  │
  ├─ try: ssm.get_parameter("/developer-briefing-agent/github-token")
  │   └─ success → return token (never touches os.environ)
  │   └─ Exception → fall back to os.environ
  │
  └─ os.environ.get("GITHUB_TOKEN")
      └─ None → error and exit
```
