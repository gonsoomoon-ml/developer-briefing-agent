# AgentCore Memory Integration — Design Spec

## Goal

Add persistent cross-session memory to the developer briefing agent so that conversations build on previous context. The agent remembers what it reported, enabling delta-aware standups, follow-up questions across sessions, and weekly summaries from accumulated context.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Memory type | Semantic (long-term) | Facts extracted via embeddings, scales without bloating context |
| Integration | Hooks (automatic) | Transparent — no new tools, no prompt changes needed |
| Scope | Per developer (`dev_name`) | Matches existing SKILL.md personalization axis |
| Target runtimes | Both local and remote | Shared hook module, identical integration |
| Degradation | Graceful | No `MEMORY_ID` = no hooks, agent works as before |

## Architecture

```
                  ┌─────────────────────────┐
                  │   AgentCore Memory      │
                  │   (AWS managed)         │
                  │                         │
                  │  namespace:             │
                  │  standup/actor/{dev}/   │
                  │          facts          │
                  └────┬──────────┬─────────┘
                       │          │
                 retrieve    create_event
                   (before)    (after)
                       │          │
              ┌────────┴──────────┴────────┐
              │  shared/memory_hooks.py    │
              │  StandupMemoryHooks        │
              │  (HookProvider)            │
              └────────┬──────────┬────────┘
                       │          │
           ┌───────────┘          └───────────┐
           │                                  │
  local-agent/                     managed-agentcore/
  strands_agent.py                 agentcore_runtime.py
  chat.py                          chat.py
```

## Components

### 1. `setup/create_memory.py`

One-time provisioning script. Creates the AgentCore memory resource with a semantic strategy.

**Input:** AWS credentials (from environment/profile), region from `AWS_REGION` or default.

**Behavior:**
- Creates memory named `"developer-briefing-memory"` with one semantic strategy:
  - Name: `"StandupFacts"`
  - Namespace: `standup/actor/{actorId}/facts`
  - `event_expiry_days`: 90
- Writes `MEMORY_ID=<id>` to both `local-agent/.env` and `managed-agentcore/.env`
- Idempotent: if memory with that name already exists, prints existing ID and updates `.env` files

**Dependencies:** `bedrock_agentcore.memory.MemoryClient`, `bedrock_agentcore.memory.constants.StrategyType`

**Run:** `uv run setup/create_memory.py`

### 2. `shared/memory_hooks.py`

The core module. A `HookProvider` subclass with two callbacks.

**Class: `StandupMemoryHooks`**

Constructor:
- `memory_id: str` — from `MEMORY_ID` env var
- `dev_name: str` — developer identity, used as `actorId`
- `region: str` — AWS region, defaults to env or `"us-west-2"`
- Creates a `MemoryClient` instance

Callback: `retrieve_context(event: MessageAddedEvent)`
- Extracts the user's query from the last message
- Calls `client.retrieve_memories()` with:
  - `namespace`: `standup/actor/{dev_name}/facts`
  - `query`: the user's message text
  - `top_k`: 5
- If results exist, prepends a `[이전 대화에서 알게 된 정보]` block to the user message content

Callback: `save_interaction(event: AfterInvocationEvent)`
- Extracts the last user + assistant message pair from `event.agent.messages`
- Calls `client.create_event()` with:
  - `actor_id`: `dev_name`
  - `session_id`: `"{dev_name}-session"`
  - `messages`: list of `(text, role)` tuples

Register: `register_hooks(registry: HookRegistry)`
- `MessageAddedEvent` -> `retrieve_context`
- `AfterInvocationEvent` -> `save_interaction`

### 3. Agent integration changes

Three files get the same minimal change — add `hooks=` parameter to `Agent()`:

**`local-agent/strands_agent.py`**
- Import `StandupMemoryHooks` from `shared.memory_hooks`
- Read `MEMORY_ID` from env
- If set, create `hooks=[StandupMemoryHooks(memory_id, dev_name)]`
- If not set, `hooks=[]`
- Pass `hooks=hooks` to `Agent()`

**`local-agent/chat.py`**
- Same pattern inside `create_agent(dev_name)`

**`managed-agentcore/agentcore_runtime.py`**
- Same pattern inside `create_agent(dev_name)`

**Import path:** Both `local-agent/` and `managed-agentcore/` scripts already resolve `PROJECT_ROOT`. They add it to `sys.path` so `from shared.memory_hooks import StandupMemoryHooks` works without package installation. For the container, the Dockerfile COPY handles it.

### 4. `--date` flag for demo simulation

Both `local-agent/chat.py` and `managed-agentcore/chat.py` accept `--date YYYY-MM-DD`.

**Behavior:**
- If provided, the system prompt includes: `"오늘은 {date} {weekday}입니다."`
- Allows simulating multiple days in a single demo session:
  ```bash
  uv run local-agent/chat.py --date 2026-04-06    # "Monday"
  uv run local-agent/chat.py --date 2026-04-07    # "Tuesday"
  uv run local-agent/chat.py --date 2026-04-10    # "Friday"
  ```
- Does NOT affect `github_standup.py` — real GitHub data is always fetched
- `local-agent/strands_agent.py` (single-shot) does not need this flag

### 5. Environment and container changes

**`local-agent/.env.example`** — add:
```
MEMORY_ID=           # AgentCore Memory ID (run setup/create_memory.py to create)
```

**`managed-agentcore/.env.example`** — add:
```
MEMORY_ID=           # AgentCore Memory ID (run setup/create_memory.py to create)
```

**`managed-agentcore/Dockerfile`** — add:
```dockerfile
COPY shared/ /app/shared/
```

### 6. `setup.sh` update

Add optional step 4 after GitHub token setup:

```
=== 단계 4/4: AgentCore 메모리 설정 (선택) ===
  1) 메모리 생성 — AgentCore에 메모리 리소스 생성
  s) 건너뛰기 — 나중에 설정
```

If chosen, runs `python setup/create_memory.py`.

## File changes summary

| File | Change |
|------|--------|
| `shared/memory_hooks.py` | **New** — StandupMemoryHooks HookProvider |
| `setup/create_memory.py` | **New** — one-time memory provisioning |
| `local-agent/strands_agent.py` | Add hooks param (3 lines) |
| `local-agent/chat.py` | Add hooks param + `--date` flag |
| `managed-agentcore/agentcore_runtime.py` | Add hooks param |
| `managed-agentcore/chat.py` | Add `--date` flag |
| `managed-agentcore/Dockerfile` | Add `COPY shared/` |
| `local-agent/.env.example` | Add `MEMORY_ID` |
| `managed-agentcore/.env.example` | Add `MEMORY_ID` |
| `setup.sh` | Add step 4 for memory setup |

## What this does NOT change

- `SKILL.md` files — memory is orthogonal to the skill system
- `github_standup.py` — still fetches real-time GitHub data
- `/switch` behavior — works naturally, hooks use the switched developer's namespace
- Agent without memory — if `MEMORY_ID` is not set, everything works exactly as before

## Demo script with memory

```
# Setup (one-time, before demo)
python setup/create_memory.py

# Demo: simulate Mon → Tue → Fri
uv run local-agent/chat.py --date 2026-04-06
> 오늘 업무 브리핑 해줘
  → 구조 개편 커밋 3건, 한국어 리팩토링 완료 ...
> 한국어 리팩토링 어디까지 했어?
  → strands_agent.py, chat.py 모두 완료 ...
> /quit

uv run local-agent/chat.py --date 2026-04-07
> 어제 이후로 뭐 바뀌었어?
  → [memory: 어제 구조 개편 3건, 한국어 리팩토링 완료]
  → 어제 이후 새 커밋 2건: 메모리 훅 추가, setup.sh 업데이트 ...
> /quit

uv run local-agent/chat.py --date 2026-04-10
> 이번 주 요약해줘
  → [memory: 월요일 구조 개편, 화요일 메모리 통합, ...]
  → 주간 요약: 총 커밋 8건, developer-briefing-agent에 집중 ...
```
