# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🛑 Action Approval Rule (HIGHEST PRIORITY)

**Before taking ANY action — including but not limited to file edits, file creation, file deletion, running scripts, installing dependencies, deploying, pushing to git, modifying `.env` files, or running any command with side effects — you MUST:**

1. **State clearly what action you are about to take** (which file, which command, which change — with specifics).
2. **Explain briefly why** this action is needed and what it will change.
3. **Ask for explicit approval** and wait for the user to confirm before proceeding.

**Do not bundle multiple actions into a single request.** If you need to make several changes, list them, get approval for the list, then execute them one at a time with status updates.

**Read-only operations** (reading files, running `git status`, searching code, listing directories) do not require approval — but anything that modifies state does.

This rule overrides any instinct to "just do it efficiently". The user prefers visibility and control over speed.

## Project Purpose

A 5-minute live demo showing **Strands Agents SDK** + **Amazon Bedrock AgentCore Runtime**. The agent writes a daily standup for a developer by fetching GitHub activity — personalized per developer via a `SKILL.md` file, with no code changes between users.

Two files tell the story:
- `local-agent/example_single_shot.py` — the entire agent, runs locally
- `managed-agentcore/agentcore_runtime.py` — async streaming wrapper that deploys it as a team service

## Commands

### Setup

```bash
bash setup.sh                        # deps install, .env creation, GitHub token setup
uv sync                              # deps only
```

Verify install:
```bash
uv run python -c "from strands import Agent; from strands_tools import shell, file_read; from bedrock_agentcore.runtime import BedrockAgentCoreApp; print('OK')"
```

### Local Agent

```bash
uv run local-agent/chat.py                       # interactive chat (default: sejong)
uv run local-agent/chat.py --dev_name sunshin     # specific developer
uv run local-agent/chat.py --date 2026-04-06      # simulate date (demo)
uv run local-agent/chat.py --debug                # memory hook debug output
uv run local-agent/example_single_shot.py               # single-shot standup
```

Chat commands: `/switch <name>` to change developer, `/quit` to exit.

### AgentCore Runtime (Remote)

```bash
uv run managed-agentcore/deploy.py       # deploy (~5-10 min first, ~40s update)
uv run managed-agentcore/example_invoke.py       # single invocation test
uv run managed-agentcore/chat.py                              # interactive chat (remote)
```

### Cross-Session Memory (Optional)

```bash
uv run setup/create_memory.py        # one-time: creates memory resource, saves MEMORY_ID to .env files
```

### Tests and Linting

No test suite or linter is configured. Verification is manual: run `chat.py` and confirm the agent produces correct standup output.

## Architecture

### Data Flow

```
User prompt → Agent(shell, file_read)
                │
                ├─ shell: runs skills/{dev_name}/scripts/github_standup.py → /tmp/standup_data.json
                ├─ file_read: reads the JSON
                └─ LLM formats response per SKILL.md rules
```

### Agent Creation Pattern (3 identical sites)

`create_agent(dev_name)` exists in three files — `local-agent/example_single_shot.py`, `local-agent/chat.py`, `managed-agentcore/agentcore_runtime.py`. All three follow the same pattern:

1. Read `prompts/system_prompt.md`, substitute `{dev_name}`
2. Read `skills/{dev_name}/SKILL.md`, substitute `{skill_dir}` with absolute path
3. Concatenate as `## Active Skill` section
4. Pass as `system_prompt=[SystemContentBlock(text=...), SystemContentBlock(cachePoint=...)]`
5. `SlidingWindowConversationManager(window_size=20)`, `cache_tools="default"`
6. If `MEMORY_ID` env var is set, attach `StandupMemoryHooks`

**When modifying Agent creation, update all three sites.**

### Multi-Turn in AgentCore

Two mechanisms work together:
1. **Module-level `_session_agents` dict** in `agentcore_runtime.py` — reuses same Agent object (preserving `agent.messages`) across requests, keyed by `"dev_name:session_id"`
2. **`runtimeSessionId`** on API call — routes to the same Firecracker microVM (same Python process → same dict)

### Memory Hooks (`shared/memory_hooks.py`)

`StandupMemoryHooks` (Strands `HookProvider`) with three callbacks:
- `retrieve_context` (BeforeInvocation) — first turn only: semantic search from AgentCore Memory. Subsequent turns: manages message-level cachePoints (moving + anchor)
- `dump_prompt` (BeforeModelCall) — debug-only prompt visualization
- `save_interaction` (AfterInvocation) — saves user-assistant pair to AgentCore Memory

Memory is opt-in: no `MEMORY_ID` → no hooks → stateless agent.

### Deploy-Time Copies

`managed-agentcore/skills/` and `managed-agentcore/shared/` are deploy-time copies (gitignored). **Source of truth is at project root** (`skills/`, `shared/`).

## Gotchas — Do Not Change

1. **Never use `AgentSkills` plugin** — its `_on_before_invocation` downcasts `agent.system_prompt` to a string, dropping `cachePoint` blocks and breaking prompt caching. Use static SKILL.md inline instead.

2. **Never set `cache_config` on Agent** — it activates `_inject_cache_point` auto-mode that strips manual cachePoints. Only `cache_tools="default"` is used.

3. **Keep system prompt above 2,048 tokens** — Claude Sonnet 4.6's minimum cache checkpoint size. `prompts/system_prompt.md` + Active Skill (~4,877 tokens combined) clears this. Don't shrink the system prompt significantly.

4. **Bedrock allows max 4 `cache_control` blocks per request** — tools(1) + system(1) + moving message cachePoint(1) + anchor cachePoint(1, conditional). `retrieve_context` in `memory_hooks.py` manages this budget; don't add cachePoints elsewhere.

5. **`SlidingWindowConversationManager(window_size=20)`** — smaller values (3, 10) break cache prefix too frequently. 20 balances token growth vs cache stability.

6. **Model is `global.anthropic.claude-sonnet-4-6`** via `BedrockModel` — the `global.` prefix enables cross-region inference.

7. **All UI text and system prompts are in Korean** — maintain this convention.

## Adding a New Developer

1. Create `skills/<name>/SKILL.md` — use `{skill_dir}` placeholder for path references
2. Copy `skills/sejong/scripts/github_standup.py` into `skills/<name>/scripts/`
3. Use `/switch <name>` in chat or set `DEV_NAME=<name>` in `.env`

No Python code change needed.

## GitHub Token

`github_standup.py` looks for the token in this order:
1. AWS SSM Parameter Store (`/developer-briefing-agent/github-token`)
2. `GITHUB_TOKEN` env var from `.env`

To set up SSM: `bash setup/store_github_token.sh`

## Reference Docs

- `docs/architecture/prompt-caching.md` — Bedrock prompt caching mechanics, measured data, optimization strategy
- `docs/architecture/cache-flow-diagram.md` — cache flow visualization
- `docs/architecture/skill-mcp-loading.md` — why static SKILL.md loading was chosen over AgentSkills plugin
- `docs/architecture/local-vs-agentcore.md` — local agent vs AgentCore Runtime comparison, sequence diagrams
- `docs/history/agentcore-session-experimentation.md` — experiment log: multi-turn fixes, cache deep dive, SlidingWindow evaluation
