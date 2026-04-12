# 메모리 아키텍처 — 로컬 에이전트 vs AgentCore Runtime

## 3계층 메모리 모델

| 계층 | 목적 | 로컬 에이전트 | AgentCore Runtime |
|------|------|--------------|-------------------|
| **1. 컨텍스트 윈도우** | 세션 내 턴별 맥락 | `agent.messages` (인프로세스) | `runtimeSessionId` → 같은 microVM |
| **2. 세션 지속성** | 재시작/라우팅 변경에서 생존 | 미사용 (데모에서 불필요) | microVM 세션 어피니티 (idle 15분, 최대 8시간) |
| **3. 크로스 세션 지능** | 날짜를 넘어 사실 기억 | AgentCore Memory (훅) | AgentCore Memory (같은 훅) |

각 계층은 다른 문제를 해결합니다. 대안이 아니라 상호 보완.

## 계층 1: 컨텍스트 윈도우 (세션 내)

### 로컬 에이전트 (`local-agent/chat.py`)

`Agent` 객체가 `while True` 루프에서 유지. Strands SDK가 `agent.messages`에 턴마다 자동 누적. 외부 저장소 불필요.

`SlidingWindowConversationManager(window_size=20)`으로 대화가 길어져도 토큰 안정 (3,000-4,000/턴). 20개 넘는 메시지는 오래된 것부터 삭제.

### AgentCore Runtime (`managed-agentcore/agentcore_runtime.py`)

`_session_agents` dict에 Agent 객체를 캐싱. `runtimeSessionId`로 같은 microVM에 라우팅되면 같은 dict → 같은 Agent → `agent.messages` 보존.

`/switch` 시 클라이언트가 `runtimeSessionId = None`으로 리셋 → 새 microVM → 새 Agent.

## 계층 2: 세션 지속성

### 로컬 에이전트

현재 미사용. Strands SDK는 `FileSessionManager`, `S3SessionManager` 등을 제공하지만, 데모에서는 불필요.

### AgentCore Runtime

microVM 세션 어피니티가 자동 처리. 같은 `runtimeSessionId` → 같은 microVM → Agent 유지.

| 설정 | 값 |
|------|-----|
| idle 타임아웃 | 15분 |
| 최대 세션 수명 | 8시간 |
| microVM 종료 후 | 메모리 sanitize, 상태 소멸 |

## 계층 3: 크로스 세션 지능 (LTM)

`shared/memory_hooks.py`의 `StandupMemoryHooks`가 구현.

**동작 흐름:**
1. `BeforeInvocationEvent` — 첫 턴에서만 AgentCore Memory에서 관련 사실 검색 (시맨틱)
2. 에이전트가 enriched 컨텍스트로 처리
3. `AfterInvocationEvent` — 매 턴마다 user-assistant 쌍을 이벤트로 저장
4. AgentCore 백그라운드에서 사실 추출 (~1분) → `standup/actor/{dev_name}/facts` 네임스페이스

**두 런타임 모두 같은 훅 사용.** 훅은 에이전트가 로컬인지 원격인지 신경 쓰지 않음 — AgentCore Memory API만 호출.

### 검색 최적화: 첫 턴에서만 검색

`retrieve_context()`는 세션의 **첫 user 턴에서만** 실행. 이후 턴은 조기 반환.

**이유:** 세션 내에서는 `agent.messages`가 전체 대화를 누적. 매 턴마다 검색하면:
- **토큰 낭비** — 이미 히스토리에 있는 내용을 ~200-500 토큰 재주입
- **중복** — 같은 사실이 2-3회 반복 (주입 컨텍스트 + 이전 턴 + 이전 응답)
- **불필요한 지연** — 턴당 ~100-200ms API 호출, 새 정보 없음

**트레이드오프:** 대화 중간에 크로스세션 질문 ("지난주에 뭐 했어?", Turn 5)이 오면 LTM 컨텍스트가 없음. 실무에서 스탠드업 워크플로는 크로스세션 질문이 거의 항상 Turn 1에서 발생하므로 허용 가능.

### 저장 방식: 턴마다 저장

`save_interaction()`은 **매 턴마다** 실행. 마지막 user+assistant 쌍을 AgentCore에 이벤트로 저장.

**세션 종료 시 한 번 저장이 아닌 이유:**

| 환경 | 문제 |
|------|------|
| 로컬 에이전트 | `/quit` 없이 터미널 종료 시 대화 전체 유실 |
| AgentCore Runtime | 명시적 종료 신호 없음 — idle 15분 후 microVM 자동 종료 |

턴마다 저장하면 프로세스 충돌, 터미널 종료, idle 타임아웃 모두 안전.

## 결정 매트릭스

| 시나리오 | 계층 1 | 계층 2 | 계층 3 |
|---------|--------|--------|--------|
| 데모 (5분, 로컬) | agent.messages | 불필요 | LTM 훅 (`--date`로 크로스데이 데모) |
| 데모 (원격, 단일 세션) | microVM 세션 어피니티 | 불필요 | LTM 훅 |
| 프로덕션 (로컬, 장시간) | + `SlidingWindowConversationManager` | + `FileSessionManager` | LTM 훅 |
| 프로덕션 (원격, 다중 사용자) | microVM 세션 어피니티 | + `memory_mode="STM_AND_LTM"` | LTM 훅 |

## 참고 자료

- [Strands — 대화 관리](https://strandsagents.com/docs/user-guide/concepts/agents/conversation-management/)
- [Strands — 세션 관리](https://strandsagents.com/docs/user-guide/concepts/agents/session-management/)
- [AgentCore Memory Session Manager](https://strandsagents.com/docs/community/session-managers/agentcore-memory/)
- [AgentCore Runtime Sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
