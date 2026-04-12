# 로컬 에이전트 vs AgentCore Runtime

동일한 Strands Agent를 두 가지 방식으로 실행합니다. 에이전트 로직(system_prompt + SKILL.md + tools)은 완전히 같고, **서빙 방식**만 다릅니다.

## 언제 어떤 것을 쓰는가

### 로컬 에이전트 (`local-agent/chat.py`)

**적합한 상황:**
- 개발자 본인이 터미널에서 직접 사용
- 개발/디버깅 중 빠른 반복 (`--debug` 플래그로 프롬프트 시각화)
- AWS 인프라 없이 GitHub 토큰만으로 동작 확인
- 데모 시 "이게 전부입니다"를 보여주는 용도

**한계:**
- 실행한 사람만 사용 가능 — 팀원에게 공유하려면 코드를 직접 실행해야 함
- 터미널을 닫으면 대화 히스토리 소실 (Memory를 쓰면 사실은 복구 가능하지만 Agent 객체는 새로 생성)
- 동시 사용자 불가

### AgentCore Runtime (`managed-agentcore/`)

**적합한 상황:**
- 팀 전체가 하나의 엔드포인트로 사용 — 각자 다른 `dev_name`으로 호출
- 항상 실행 중인 서비스 — 터미널 세션에 의존하지 않음
- Slack 봇, 웹 UI, CI/CD 파이프라인 등 다른 시스템에서 HTTP로 호출
- 세션 격리 — 사용자별 전용 microVM으로 보안/성능 격리

**추가 비용:**
- Docker 빌드 + ECR 푸시 + AgentCore Runtime 프로비저닝 필요 (첫 배포 ~5-10분)
- IAM 역할, SSM 권한 등 AWS 인프라 설정
- microVM cold start 지연 (~수초)

### 요약: 왜 AgentCore가 필요한가

로컬 에이전트는 **"나 혼자 쓰는 도구"**, AgentCore는 **"팀이 쓰는 서비스"**입니다.

```
로컬:    개발자 → 터미널 → Agent → 결과
AgentCore: 개발자A ─┐
           개발자B ──┤→ HTTP 엔드포인트 → microVM(각각) → Agent → SSE 응답
           Slack 봇 ─┘
```

## 핵심 차이 비교

| | 로컬 (`local-agent/chat.py`) | 원격 (`managed-agentcore/agentcore_runtime.py`) |
|---|---|---|
| Agent 생성 위치 | `main()` 안에서 1회 | `create_agent()` 함수 — 첫 요청 시 호출 |
| Agent 저장 | Python 변수 `agent` | `_session_agents` dict (키: `"dev_name:session_id"`) |
| Agent 재사용 | 같은 변수를 while 루프에서 재사용 | `_get_or_create_agent()`로 dict에서 조회 |
| 멀티턴 보장 | 같은 프로세스 안이라 자동 | `runtimeSessionId`로 같은 microVM 라우팅 |
| 출력 | `print(data, end="")` | `yield {"type": "agent_text_stream", ...}` (SSE) |
| 경로 폴백 | 불필요 (항상 프로젝트 루트) | 2단 폴백 (컨테이너 내 / 프로젝트 루트) |
| session_id | 없음 | `StandupMemoryHooks`에 전달하여 Memory 이벤트 그룹화 |

## 시퀀스 다이어그램

### 로컬 에이전트 — 멀티턴 대화

```
사용자          chat.py              Agent 객체            Strands SDK           Bedrock LLM
  │                │                    │                     │                     │
  │ 프로그램 시작   │                    │                     │                     │
  │───────────────>│                    │                     │                     │
  │                │ create_agent()     │                     │                     │
  │                │───────────────────>│ (agent 변수에 저장)  │                     │
  │                │                    │                     │                     │
  │ "오늘 브리핑"   │                    │                     │                     │
  │───────────────>│ stream_async()     │                     │                     │
  │                │───────────────────>│ messages에 append   │                     │
  │                │                    │────────────────────>│ LLM 호출            │
  │                │                    │                     │────────────────────>│
  │                │                    │                     │ 텍스트 스트리밍      │
  │                │ print(data)        │                     │<────────────────────│
  │<───────────────│<───────────────────│<────────────────────│                     │
  │                │                    │                     │                     │
  │ "PR 있어?"     │                    │                     │                     │
  │───────────────>│ stream_async()     │                     │                     │
  │                │───────────────────>│ messages에 append   │                     │
  │                │                    │ (이전 대화 포함)     │ LLM 호출            │
  │                │                    │────────────────────>│────────────────────>│
  │                │ print(data)        │                     │ 맥락 있는 응답       │
  │<───────────────│<───────────────────│<────────────────────│<────────────────────│
  │                │                    │                     │                     │
  │ /switch sunshin│                    │                     │                     │
  │───────────────>│ create_agent()     │                     │                     │
  │                │───────────────────>│ (새 Agent, 빈 messages)                   │
  │                │ agent = 새 객체    │                     │                     │
```

핵심: `agent` **변수 1개**를 while 루프에서 재사용. `/switch`만 새 Agent 생성.

### AgentCore Runtime — 멀티턴 대화

```
클라이언트(chat.py)     AgentCore 서비스        microVM / agentcore_runtime.py     Bedrock LLM
  │                        │                        │                                │
  │ invoke(payload)        │                        │                                │
  │ (runtimeSessionId 없음)│                        │                                │
  │───────────────────────>│ 새 microVM 프로비저닝   │                                │
  │                        │───────────────────────>│ Python 프로세스 시작             │
  │                        │                        │ _session_agents = {}             │
  │                        │                        │                                │
  │                        │ payload 전달           │                                │
  │                        │───────────────────────>│ @app.entrypoint 호출            │
  │                        │                        │ _get_or_create_agent()          │
  │                        │                        │ → dict 미스 → create_agent()    │
  │                        │                        │ → dict에 저장                   │
  │                        │                        │ agent.stream_async()            │
  │                        │                        │───────────────────────────────>│
  │ SSE: text 스트리밍      │                        │                                │
  │<───────────────────────│<───────────────────────│<───────────────────────────────│
  │ SSE: workflow_complete  │                        │                                │
  │<───────────────────────│ runtimeSessionId=X 반환│                                │
  │                        │                        │                                │
  │ invoke(payload,        │                        │                                │
  │  runtimeSessionId=X)   │                        │                                │
  │───────────────────────>│ X로 같은 microVM 라우팅│                                │
  │                        │───────────────────────>│ @app.entrypoint 호출            │
  │                        │                        │ _get_or_create_agent()          │
  │                        │                        │ → dict 히트 → 기존 Agent 반환   │
  │                        │                        │ agent.messages에 이전 대화 있음  │
  │                        │                        │ agent.stream_async()            │
  │                        │                        │───────────────────────────────>│
  │ SSE: 맥락 있는 응답     │                        │                                │
  │<───────────────────────│<───────────────────────│<───────────────────────────────│
  │                        │                        │                                │
  │ /switch → runtimeSessionId = None                                                │
  │ invoke(payload)        │                        │                                │
  │ (runtimeSessionId 없음)│ 새 microVM 프로비저닝   │                                │
  │───────────────────────>│───────────────────────>│ 새 프로세스, 빈 dict             │
```

핵심: **2개 계층**이 협력하여 멀티턴을 구현.
1. AgentCore 인프라: `runtimeSessionId`로 같은 microVM 라우팅
2. 애플리케이션: `_session_agents` dict로 같은 Agent 객체 반환

## microVM 세션 모델 (1 microVM = 1 세션)

AWS 공식 문서에 따르면:

> "AgentCore Runtime provisions a **dedicated execution environment (microVM) for each session**."
> — [Use isolated sessions for agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)

| 동작 | 결과 |
|------|------|
| 새 `runtimeSessionId` (또는 미전송) | 새 microVM 프로비저닝 (cold start 발생) |
| 같은 `runtimeSessionId` 재전송 | 같은 microVM으로 라우팅 (상태 보존) |
| 세션 종료 후 같은 ID 재전송 | 새 microVM 생성 (이전 상태 소멸) |

세션 수명: idle 15분 후 종료, 최대 8시간. 종료 시 microVM 전체 삭제 + 메모리 sanitize.

## `_session_agents` dict가 필요한 이유

1 microVM = 1 세션이므로 dict에는 보통 키가 1개만 존재합니다. 그럼에도 dict를 사용하는 이유:

1. **`dev_name`이 런타임에 결정됨** — 모듈 로딩 시점에는 어떤 개발자가 요청할지 알 수 없습니다. 첫 요청의 payload에서 `dev_name`을 받아야 Agent를 생성할 수 있으므로 모듈 레벨 Agent는 불가능합니다.
2. **`@app.entrypoint`는 매 요청마다 호출됨** — HTTP 요청-응답 사이클이므로 함수 지역 변수는 매번 사라집니다. Agent 객체를 요청 간 유지하려면 모듈 레벨 저장소(dict 또는 전역 변수)가 필요합니다.
3. **방어적 설계** — 같은 microVM에 다른 `dev_name` 요청이 올 가능성에 대비. 실제로는 1세션=1개발자이지만, dict는 이 가정이 깨져도 안전하게 동작합니다.

## 경로 폴백이 필요한 이유

AgentCore Runtime은 Docker 컨테이너에서 실행됩니다. `deploy.py`가 배포 시 프로젝트 루트의 `skills/`, `shared/`, `prompts/`를 `managed-agentcore/` 안으로 복사합니다 (Docker 빌드 컨텍스트에 포함하기 위해).

```
컨테이너:    SCRIPT_DIR / "skills" / dev_name      ← 복사본 존재
로컬 개발:   SCRIPT_DIR.parent / "skills" / dev_name ← 프로젝트 루트
```

`agentcore_runtime.py`의 `create_agent()`는 두 경로를 순서대로 시도합니다. 로컬 `chat.py`는 항상 프로젝트 루트만 사용하므로 폴백이 불필요합니다.

## 공통 부분 (변하지 않는 것)

두 방식 모두 동일:
- Agent 설정: `BedrockModel`, `cache_tools="default"`, `SlidingWindowConversationManager(window_size=20)`
- 시스템 프롬프트: `system_prompt.md` + `SKILL.md` 결합, `cachePoint` 블록 포함
- 도구: `[shell, file_read]`
- 메모리 훅: `MEMORY_ID` 있으면 `StandupMemoryHooks` 등록
- SKILL.md 처리: YAML frontmatter strip, `{skill_dir}` 절대 경로 치환
