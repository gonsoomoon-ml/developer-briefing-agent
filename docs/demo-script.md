# Demo Script & Chat Commands

## Chat Commands

```bash
# Start chat (default: sejong)
uv run local-agent/chat.py

# Start with specific developer
uv run local-agent/chat.py --dev_name sunshin
```

| Command | Description |
|---------|-------------|
| `/switch <name>` | Switch developer (e.g. `/switch sunshin`) |
| `/quit` or `quit` | Exit |

## Useful Prompts

| Prompt | What it does |
|--------|-------------|
| 오늘 업무 브리핑 해줘 | Full standup briefing |
| 리뷰할 PR 있어? | Check open PRs to review |
| 이번 주 뭐 했는지 알려줘 | This week's activity summary |
| 오늘 할 일 알려줘 | Today's tasks |

## 5-Minute Demo Script

### Act 1: The Agent (0–1 min)

Open `local-agent/strands_agent.py` and show:
- 20 lines total
- `Agent()` with `tools=[shell, file_read]` and `plugins=[AgentSkills(...)]`
- "The entire agent is this one file"

### Act 2: The Personalization (1–2 min)

Open `skills/sejong/SKILL.md`:
- Format: 3 bullets, blockers-first
- Repos: analyze-claude-code, developer-briefing-agent
- "No code changes — just a markdown file"

### Act 3: Run Sejong (2–3 min)

```
$ uv run local-agent/chat.py

==================================================
  Developer Briefing Agent (sejong)
==================================================

> 오늘 업무 브리핑 해줘

(streaming output — 3 bullets, blockers-first, concise)

> 리뷰할 PR 있어?

(follow-up uses conversation context — no re-fetching)
```

Key talking point: "Same code, streaming output, conversation context preserved"

### Act 4: Switch to Sunshin (3–4 min)

Show `skills/sunshin/SKILL.md`:
- Format: numbered list (What I shipped / What I'm building / What I need)
- Different repos: sample-deep-insight, claude-extensions
- "Different markdown file, completely different output"

```
> /switch sunshin
Switched to sunshin

> 순신의 업무 브리핑 해줘

(streaming output — numbered list, detailed, PR links included)

> 리뷰할 PR 있어?

(shows PR #45 with clickable link — Sejong had none)
```

Key talking point: "Zero code changes. Same agent, different SKILL.md, completely different behavior"

### Act 5: Deploy as Team Service (4–5 min)

Show `managed-agentcore/agentcore_runtime.py`:
- Wraps the same agent with `@app.entrypoint`
- Accepts `dev_name` per request — one runtime serves all developers

```bash
# Deploy (already done before demo — takes 5 min)
uv run managed-agentcore/01_create_agentcore_runtime.py

# Invoke as team service
uv run managed-agentcore/02_invoke_agentcore_runtime.py
uv run managed-agentcore/02_invoke_agentcore_runtime.py --dev_name sunshin
```

Key talking point: "One command to deploy. Now the whole team uses it"

## Demo Contrast Summary

| | Sejong | Sunshin |
|---|---|---|
| Format | 3 bullets | Numbered list |
| Detail | Under 15 words per bullet | 2 sentences per item |
| Repos | analyze-claude-code, developer-briefing-agent | sample-deep-insight, claude-extensions |
| PR links | No | Always included |
| Blocker placement | Leads when present | Always under "What I need" |
| Open PRs | None | PR #45 (jesamkim) |
