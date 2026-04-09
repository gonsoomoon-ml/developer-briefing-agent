# Memory Architecture — Local Agent vs AgentCore Runtime

## 3-Layer Memory Model

| Layer | Purpose | Local Agent | AgentCore Runtime |
|-------|---------|-------------|-------------------|
| **1. Context Window** | In-session turn-by-turn context | Strands `agent.messages` (in-process) | Runtime session affinity (microVM) |
| **2. Session Persistence** | Survive restarts / route changes | `FileSessionManager` or none | `runtimeSessionId` header → same microVM |
| **3. Cross-Session Intelligence** | Remember facts across days | AgentCore LTM via hooks | AgentCore LTM via hooks |

Each layer solves a different problem. They are complementary, not alternatives.

## Layer 1: Context Window (Within-Session)

### Local Agent (`local-agent/chat.py`)

The `Agent` object persists in the `while True` loop. Strands accumulates messages in `agent.messages` across turns. No external storage needed.

**Risk:** Long sessions can exceed the model's token limit. Mitigate with `ConversationManager`:
- `SlidingWindowConversationManager(window_size=50)` — drops oldest messages
- `SummarizingConversationManager` — summarizes old messages instead of dropping

Currently not configured. Works fine for short demo sessions.

### AgentCore Runtime (`managed-agentcore/agentcore_runtime.py`)

**Current:** Creates a new agent per request in `@app.entrypoint`. Each turn is stateless.

**Better:** AgentCore Runtime supports session affinity via microVMs. If the client sends `runtimeSessionId` header, requests route to the same microVM where the agent object (and its messages) persist in memory. Sessions last up to 8 hours, 15-minute idle timeout.

This means the remote agent can behave exactly like the local agent — accumulating messages across turns within a session — without any explicit memory integration.

**To implement:** Move agent creation outside `@app.entrypoint` or cache agents per session ID.

## Layer 2: Session Persistence

### Local Agent

Options (not currently used):
- `FileSessionManager(session_id="sejong")` — persists agent state to disk, survives restarts
- `S3SessionManager` — same but to S3
- `AgentCoreMemorySessionManager` — uses AgentCore STM

For a demo, not needed. For production, `FileSessionManager` is the simplest.

### AgentCore Runtime

Session affinity handles this automatically. The microVM keeps the agent alive across requests within a session. If the microVM is recycled, the session is lost — use AgentCore STM (`memory_mode="STM_ONLY"` or `"STM_AND_LTM"`) for durability.

## Layer 3: Cross-Session Intelligence (LTM)

This is what our `shared/memory_hooks.py` implements.

**How it works:**
1. `BeforeInvocationEvent` — retrieves relevant facts from AgentCore Memory (first turn only)
2. Agent processes with enriched context
3. `AfterInvocationEvent` — saves the user-assistant exchange as an event
4. AgentCore background job extracts facts (~1 min) into `standup/actor/{dev_name}/facts` namespace

**Same hooks work for both runtimes.** The hooks don't care whether the agent is local or remote — they just talk to AgentCore Memory API.

**Strategy:** `SEMANTIC` — stores extracted facts as vector embeddings, retrieved by natural language similarity.

### Retrieval Optimization: First Turn Only

`retrieve_context()` only runs on the **first user turn** of a session. On subsequent turns, it returns early.

**Why:** Within a session, `agent.messages` already accumulates the full conversation. Retrieving on every turn causes:
- **Token waste** — each retrieval injects ~200-500 tokens of context that's already in message history
- **Duplication** — model sees the same facts 2-3x (injected context + earlier turns + earlier responses)
- **Unnecessary latency** — ~100-200ms API call per turn with no new information

**Trade-off:** If a user asks a cross-session question mid-conversation ("지난주에 뭐 했어?" on Turn 5), the agent won't have LTM context for it. In practice this is rare for standup workflows — cross-session queries almost always come at Turn 1.

**Detection:** Counts user messages in `agent.messages`. If more than one user message exists, the session is already underway and retrieval is skipped.

```python
# 첫 번째 턴에서만 검색
user_messages = [m for m in messages if m["role"] == "user"]
if len(user_messages) > 1:
    return
```

### Save Behavior: Per-Turn Events

`save_interaction()` fires on **every turn**, saving the last user+assistant pair to AgentCore as an event. AgentCore accumulates these events per `session_id` and extracts facts from the aggregate.

Alternative considered: save the full conversation once at session end (`/quit`). This would give AgentCore better context for extraction, but:
- Cannot hook into `/quit` from `HookProvider` — it's chat-loop logic, not agent lifecycle
- If the process crashes, all unsaved turns are lost
- Per-turn saving is "good enough" — AgentCore groups events by `session_id`

## Decision Matrix

| Scenario | Layer 1 | Layer 2 | Layer 3 |
|----------|---------|---------|---------|
| Demo (5 min, local) | In-process messages | Not needed | LTM hooks (for cross-day demo with `--date`) |
| Demo (remote, single session) | Runtime session affinity | Not needed | LTM hooks |
| Production (local, long sessions) | + `SlidingWindowConversationManager` | + `FileSessionManager` | LTM hooks |
| Production (remote, multi-user) | Runtime session affinity | + `memory_mode="STM_AND_LTM"` | LTM hooks |

## Key Strands Components

### ConversationManager (Layer 1)

Manages what messages stay in the model's context window.

```python
from strands.agent.conversation_manager import SlidingWindowConversationManager

agent = Agent(
    conversation_manager=SlidingWindowConversationManager(window_size=50),
    ...
)
```

### SessionManager (Layer 2)

Persists full agent state to external storage.

```python
from strands.session import FileSessionManager

agent = Agent(
    session_manager=FileSessionManager(session_id="sejong-2026-04-09"),
    ...
)
```

### HookProvider (Layer 3 — our implementation)

Retrieves/saves cross-session context via AgentCore Memory API.

```python
from shared.memory_hooks import StandupMemoryHooks

agent = Agent(
    hooks=[StandupMemoryHooks(memory_id, dev_name)],
    ...
)
```

## AgentCore Runtime Sessions

When `runtimeSessionId` is passed by the client, AgentCore routes all requests to the same microVM:

```python
# Client side (chat.py)
response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    runtimeSessionId="sejong-session-001",  # ← enables session affinity
    payload=payload,
)
```

The server-side agent persists across invocations within that session. No code changes needed in `agentcore_runtime.py` — session affinity is a runtime feature.

**Limits:**
- Max session duration: 8 hours
- Idle timeout: 15 minutes (configurable via `idle_timeout` in `configure()`)
- Max lifetime: configurable via `max_lifetime` in `configure()`

## References

- [Strands — Conversation Management](https://strandsagents.com/docs/user-guide/concepts/agents/conversation-management/)
- [Strands — Session Management](https://strandsagents.com/docs/user-guide/concepts/agents/session-management/)
- [AgentCore Memory Session Manager](https://strandsagents.com/docs/community/session-managers/agentcore-memory/)
- [AgentCore Runtime Sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
- [AgentCore STM with Strands (DEV Community)](https://dev.to/aws-heroes/amazon-bedrock-agentcore-runtime-part-6-using-agentcore-short-term-memory-with-strands-agents-sdk-55d4)
- [AgentCore LTM with Strands (DEV Community)](https://dev.to/aws-heroes/amazon-bedrock-agentcore-runtime-part-7-using-agentcore-long-term-memory-with-strands-agents-sdk-lb2)
- [Hybrid Memory with Strands (DEV Community)](https://dev.to/aws/never-forget-a-thing-building-ai-agents-with-hybrid-memory-using-strands-agents-2g66)
