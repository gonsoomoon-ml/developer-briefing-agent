# Developer Briefing Agent

▶️ [데모 영상 보기](https://youtu.be/ik81VLbV5W4)

매일 아침, 팀의 각 개발자에게 맞춤 브리핑을 만들어주는 AI 에이전트.
개발자마다 `SKILL.md` 파일 하나만 작성하면, 코드 변경 없이 자기만의 브리핑 형식이 생깁니다.

---

## 왜 만들었는가

GitHub 활동 데이터로 개발자별 스탠드업 브리핑을 자동 생성하며,
개발자별 개인화(브리핑 형식, 담당 Git repo)는 `SKILL.md` 하나로 정의됩니다.
Python 코드 변경 없이 새 개발자를 추가할 수 있습니다.

**Strands Agents SDK** + **Amazon Bedrock AgentCore Runtime**으로 만들었습니다.

### 무엇을 보여주는가

1. **SKILL.md 하나로 개인화** — 개발자마다 브리핑 형식과 담당 Git repo를 마크다운으로 정의. 코드 변경 없이 새 개발자 추가.
2. **로컬에서 만들고, 원격으로 배포** — `local-agent/chat.py`로 터미널에서 테스트 → `managed-agentcore/deploy.py`로 팀 서비스화. 에이전트 로직은 동일.
3. **하나의 런타임, 전체 팀 지원** — AgentCore Runtime 하나에 `dev_name`만 바꿔 요청하면 각 개발자의 SKILL.md가 로드됨.

---

## 아키텍처 개요

```
사용자 프롬프트
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Agent(tools=[shell, file_read])                        │
│                                                         │
│  system_prompt = system_prompt.md + SKILL.md (inline)   │
│                                                         │
│  ┌─────────────────────────────────────────────┐        │
│  │ 1. shell → github_standup.py                │        │
│  │    └─ GitHub REST API → /tmp/standup_data.json       │
│  │ 2. file_read → JSON 로드                    │        │
│  │ 3. LLM이 SKILL.md 규칙대로 브리핑 생성      │        │
│  └─────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
    │
    ▼
스탠드업 브리핑 (스트리밍 출력)
```

**로컬 실행**: `chat.py` → Agent → 결과를 터미널에 출력

**원격 배포**: `agentcore_runtime.py` → 같은 Agent를 `@app.entrypoint`로 래핑 → HTTP/SSE로 팀 전체 서비스

---

## 핵심 기술 기능

| 기능 | 설명 |
|------|------|
| **SKILL.md 개인화** | 개발자별 형식, 담당 저장소, PR 트리아지 규칙을 마크다운으로 정의 |
| **Prompt Caching** | 시스템 프롬프트 + Active Skill을 Bedrock 캐시에 올려 비용 절감 |
| **멀티턴 세션** | 대화 컨텍스트를 유지하며 후속 질문 가능 |
| **크로스 세션 메모리** | AgentCore Memory로 이전 대화의 사실을 시맨틱 검색 |
| **SSE 스트리밍** | AgentCore Runtime에서 실시간 토큰 단위 응답 전달 |
| **SlidingWindow** | 대화가 길어져도 토큰 사용량 안정 유지 |

### SKILL.md 개인화

개발자별 `skills/{dev_name}/SKILL.md` 하나가 에이전트의 전체 행동을 결정합니다. Python 코드는 동일하게 유지됩니다.

```
skills/
├── sejong/
│   ├── SKILL.md          ← 3 bullets, 블로커 우선, 간결
│   └── scripts/github_standup.py
└── sunshin/
    ├── SKILL.md          ← 번호 목록, PR 트리아지 규칙, 상세
    └── scripts/github_standup.py
```

SKILL.md에 정의하는 것들:
- **응답 형식** — 3 bullets vs 번호 목록 vs 자유 형식
- **담당 저장소** — 어떤 GitHub repo를 모니터링할지
- **PR 트리아지 규칙** — dependabot PR을 위험/일반으로 자동 분류
- **스크립트 경로** — `{skill_dir}` 플레이스홀더로 포터블 경로 참조

### Prompt Caching

시스템 프롬프트 + Active Skill (~4,877 토큰)을 `cachePoint`로 마킹하면, Bedrock가 이 prefix를 캐시합니다. Turn 2부터 캐시된 부분은 **90% 비용 할인**으로 재사용됩니다.

```
Turn 1: [system+skill] Write (1.25x) → 캐시에 저장
Turn 2: [system+skill] Read  (0.1x)  → 캐시에서 읽기 ← 90% 절감
Turn 3: [system+skill+T1+T2] Read    → 누적 절감 효과 증가
```

3-Layer 캐싱 구조:
1. **도구 정의** — `cache_tools="default"`로 shell, file_read 스키마 캐시
2. **시스템 프롬프트** — 시스템 프롬프트 + SKILL.md를 명시적 `cachePoint`로 캐시
3. **턴 경계** — 이전 턴 대화를 이동형 `cachePoint`로 캐시 (Turn 2+)

4턴 세션 기준 ~52% 비용 절감. 장기 세션에서 60-80%까지 증가.

→ 상세: [`docs/architecture/prompt-caching.md`](docs/architecture/prompt-caching.md)

### 멀티턴 세션

한 번의 질문으로 끝나지 않고, 대화 맥락을 유지하며 후속 질문이 가능합니다.

```
> 오늘 업무 브리핑 해줘
(GitHub 데이터 수집 → 스탠드업 생성)

> 리뷰할 PR 있어?
(데이터 재수집 없이 이미 수집된 정보로 답변)

> 그 PR 중에 긴급한 거 있어?
(이전 답변 컨텍스트를 참고하여 트리아지)
```

- **로컬**: 같은 `Agent` 객체의 `agent.messages`에 자동 누적
- **AgentCore**: `runtimeSessionId`로 같은 microVM에 라우팅 → `_session_agents` dict에서 같은 Agent 반환

→ 상세: [`docs/architecture/local-vs-agentcore.md`](docs/architecture/local-vs-agentcore.md)

### 크로스 세션 메모리

AgentCore Memory를 통해 세션이 끝나도 이전 대화의 사실을 기억합니다.

```
[세션 1] > 오늘 업무 브리핑 해줘
         → PR #48 리뷰 필요하다고 브리핑

[세션 2] > 아까 얘기한 PR 어떻게 됐어?
         → "이전 세션에서 PR #48을 논의하셨는데..." (기억!)
```

동작 방식:
1. **저장** — 매 턴마다 user-assistant 쌍을 AgentCore Memory에 이벤트로 저장
2. **검색** — 새 세션 첫 턴에서 시맨틱 검색으로 관련 사실 5건을 사용자 메시지에 주입
3. **활성화** — `MEMORY_ID` 환경변수 하나로 on/off. 코드 변경 없음

→ 상세: [`docs/architecture/memory-architecture.md`](docs/architecture/memory-architecture.md)

### SSE 스트리밍

AgentCore Runtime에서 `yield`로 실시간 텍스트를 전달합니다. 클라이언트는 토큰 단위로 응답을 수신하여 체감 지연 시간이 크게 줄어듭니다.

```python
# agentcore_runtime.py
async for event in agent.stream_async(prompt):
    if "data" in event:
        yield {"type": "agent_text_stream", "content": event["data"]}
```

### SlidingWindow

`SlidingWindowConversationManager(window_size=20)`으로 대화가 길어져도 토큰 사용량이 안정적입니다 (3,000-4,000 토큰/턴). 20개를 초과하는 오래된 메시지는 자동 삭제되며, 캐시 prefix 안정성도 유지됩니다.

---

## 프로젝트 구조

```
developer-briefing-agent/
├── local-agent/                  # 로컬 실행
│   ├── chat.py                   #   대화형 채팅 (메인 진입점)
│   └── example_single_shot.py    #   단일 실행 예제
├── managed-agentcore/            # AgentCore Runtime 배포
│   ├── agentcore_runtime.py      #   런타임 엔트리포인트
│   ├── deploy.py                 #   배포 스크립트
│   ├── chat.py                   #   원격 대화형 채팅
│   ├── example_invoke.py         #   단일 호출 테스트
│   └── Dockerfile
├── skills/                       # 개발자별 SKILL.md + 스크립트
│   ├── sejong/                   #   sejong: 3 bullets, 간결
│   └── sunshin/                  #   sunshin: 번호 목록, PR 트리아지
├── shared/                       # 공통 모듈
│   └── memory_hooks.py           #   크로스 세션 메모리 훅
├── prompts/                      # 시스템 프롬프트
│   └── system_prompt.md
├── setup/                        # 초기 설정
│   ├── create_memory.py          #   AgentCore Memory 프로비저닝
│   └── store_github_token.sh     #   SSM에 GitHub 토큰 저장
├── docs/                         # 문서
│   ├── architecture/             #   기술 아키텍처
│   ├── demo/                     #   데모 스크립트
│   └── history/                  #   설계 스펙, 실험 기록
└── setup.sh                      # 원클릭 초기 설정
```

---

## 전제 조건

| 항목 | 요구 사항 |
|------|----------|
| Python | 3.11 이상 |
| [uv](https://docs.astral.sh/uv/) | Python 패키지 매니저 |
| AWS 계정 | Bedrock 모델 액세스 활성화 (`anthropic.claude-sonnet-4-6`) |
| AWS CLI | `aws configure`로 자격 증명 설정 완료 |
| GitHub PAT | `repo` + `read:user` 권한 ([생성 방법](https://github.com/settings/tokens)) |

AgentCore Runtime 배포 시 추가로 필요:
- Docker (이미지 빌드 + ECR 푸시)
- IAM에 AgentCore, ECR, SSM 권한

---

## 빠른 시작

```bash
bash setup.sh                        # 의존성 설치, .env 생성, GitHub 토큰 설정
uv run local-agent/chat.py           # 대화형 채팅 (로컬)
```

### 출력 예시

```
==================================================
  개발자 브리핑 에이전트 (sejong)
==================================================

> 오늘 업무 브리핑 해줘

📋 sejong님의 스탠드업 (2026-04-13 일요일)

• 이번 주 한 일: developer-briefing-agent 프로젝트 아키텍처 문서 정리 (7건 커밋),
  프롬프트 캐싱 최적화 및 검증 완료
• 오늘 할 일: AgentCore Runtime 배포 테스트, 문서 마무리
• 블로커: 없음
```

### 같은 코드, 다른 SKILL.md → 다른 출력

`/switch sunshin`으로 개발자를 전환하면, 코드 변경 없이 완전히 다른 형식으로 브리핑합니다:

```
==================================================
  개발자 브리핑 에이전트 (sunshin)
==================================================

> 오늘 업무 브리핑 해줘

📋 sunshin님의 스탠드업 (2026-04-13 일요일)

1. What I shipped
   sample-deep-insight 데이터 파이프라인 리팩토링 완료, CloudFront 배포 옵션 PR 검토

2. What I'm building
   claude-extensions에 새 확장 모듈 추가 작업 진행 중

3. What I need (PR reviews)
   - #45 (jesamkim) CloudFront + Cognito 배포 옵션 — merge 대기
   - ⚠️ #47 langchain-core 1.1.3 → 1.2.28 (dependabot) — major bump, breaking change 검토 필요
   - ⚠️ #46 cryptography 46.0.3 → 46.0.7 (dependabot) — 보안 패키지
   - 📦 Routine dependency updates: 22 open (streamlit, tornado, pyjwt, orjson, ...)
```

sejong은 **3 bullets, 블로커 우선, 간결**. sunshin은 **번호 목록, PR 트리아지 규칙, 상세**. 차이는 오직 `SKILL.md`입니다.

## 로컬 채팅

```bash
uv run local-agent/chat.py                       # 기본값: sejong
uv run local-agent/chat.py --dev_name sunshin     # 개발자 지정
uv run local-agent/chat.py --date 2026-04-06      # 날짜 시뮬레이션
uv run local-agent/chat.py --debug                # 메모리 훅 + 프롬프트 디버그 출력
```

| 명령 | 설명 |
|------|------|
| `/switch <name>` | 개발자 전환 (예: `/switch sunshin`) |
| `/quit` | 종료 |

유용한 프롬프트: `오늘 업무 브리핑 해줘`, `리뷰할 PR 있어?`, `이번 주 뭐 했는지 알려줘`

## AgentCore Runtime 배포

```bash
uv run managed-agentcore/deploy.py                # 배포 (~5-10분 첫 배포, ~40초 업데이트)
uv run managed-agentcore/example_invoke.py        # 단일 호출 테스트
uv run managed-agentcore/chat.py                  # 대화형 채팅 (원격)
```

하나의 런타임으로 모든 개발자 지원 — `dev_name`을 payload로 전달하면 해당 개발자의 `SKILL.md`가 로드됩니다.

```
# 원격에서도 로컬과 동일한 출력
$ uv run managed-agentcore/chat.py --dev_name sunshin

==================================================
  개발자 브리핑 에이전트 (sunshin)
  AgentCore Runtime 원격 호출
==================================================

> 오늘 업무 브리핑 해줘

(로컬 chat.py와 동일한 출력 — 번호 목록, PR 트리아지 포함)
```

에이전트 로직은 `local-agent/chat.py`와 완전히 동일합니다. 서빙 방식만 다릅니다.

---

## 크로스 세션 메모리 (선택)

```bash
uv run setup/create_memory.py        # 한 번만 실행 — MEMORY_ID를 .env에 자동 저장
```

`MEMORY_ID`가 설정되면 에이전트가 이전 대화를 기억합니다. 없으면 무상태로 동작.

`--date` 플래그로 여러 날을 시뮬레이션할 수 있습니다:

```bash
uv run local-agent/chat.py --date 2026-04-06    # "월요일" 브리핑
uv run local-agent/chat.py --date 2026-04-07    # "화요일" — 월요일을 기억
uv run local-agent/chat.py --date 2026-04-10    # "금요일" — 주간 요약
```

## 개발자 추가

1. `skills/<name>/SKILL.md` 작성 — 형식, 담당 저장소, `{skill_dir}` 플레이스홀더 사용
2. `skills/sejong/scripts/github_standup.py`를 `skills/<name>/scripts/`에 복사
3. `/switch <name>` 또는 `DEV_NAME=<name>`으로 사용

Python 코드 변경 불필요. 기존 SKILL.md (`skills/sejong/`, `skills/sunshin/`)를 참고하세요.

---

## 환경 변수

### local-agent/.env

| 변수 | 설명 |
|------|------|
| `GITHUB_TOKEN` | GitHub PAT (`repo` + `read:user` 권한) — SSM 또는 `.env` 둘 다 지원 |
| `DEV_NAME` | 개발자 이름 — `sejong` 또는 `sunshin` |
| `STRANDS_NON_INTERACTIVE` | `true` — shell 툴 확인 프롬프트 비활성화 |
| `MEMORY_ID` | AgentCore Memory ID (선택, `create_memory.py`가 자동 설정) |

### managed-agentcore/.env

| 변수 | 설명 |
|------|------|
| `AWS_REGION` | AWS 리전 |
| `DEV_NAME` | 기본 개발자 이름 |
| `RUNTIME_ARN` | AgentCore Runtime ARN (`deploy.py`가 자동 설정) |
| `MEMORY_ID` | AgentCore Memory ID (선택, `create_memory.py`가 자동 설정) |

### GitHub 토큰

`github_standup.py`는 토큰을 SSM Parameter Store에서 먼저 조회하고, 실패 시 `.env`의 `GITHUB_TOKEN`으로 폴백합니다.

```bash
bash setup/store_github_token.sh     # SSM에 SecureString으로 저장 (권장)
```

---

## 문서

| 문서 | 내용 |
|------|------|
| [`docs/architecture/prompt-caching.md`](docs/architecture/prompt-caching.md) | Bedrock 프롬프트 캐싱 메커니즘, 실측 데이터, 최적화 전략 |
| [`docs/architecture/agent-execution-flow.md`](docs/architecture/agent-execution-flow.md) | 에이전트 실행 흐름, 프롬프트 구조, 보안 경계 |
| [`docs/architecture/skill-mcp-loading.md`](docs/architecture/skill-mcp-loading.md) | 정적 vs 동적 SKILL.md 로딩 결정 근거 |
| [`docs/architecture/local-vs-agentcore.md`](docs/architecture/local-vs-agentcore.md) | 로컬 vs AgentCore Runtime 비교, 시퀀스 다이어그램 |
| [`docs/architecture/memory-architecture.md`](docs/architecture/memory-architecture.md) | 3계층 메모리 모델 (컨텍스트/세션/LTM) |
| [`docs/demo/demo-script.md`](docs/demo/demo-script.md) | 데모 스크립트, 채팅 명령어 |
