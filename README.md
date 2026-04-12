# Developer Briefing Agent

개발자마다 하나의 에이전트 — 동일한 코드, 다른 `SKILL.md` → 완전히 다른 출력.

---

## 왜 만들었는가

**Strands Agents SDK** + **Amazon Bedrock AgentCore Runtime**의 5분 라이브 데모용 프로젝트입니다.

> "오후 반나절이면 에이전트를 만들 수 있습니다. 한 번 배포하면 팀 전체가 사용합니다."

GitHub 활동 기반 일일 스탠드업을 유스케이스로 선택했습니다 — 모든 개발자가 매일 하는 일이라 공감하기 쉽고, 개발자별 개인화(형식, 담당 저장소, 상세도)의 효과를 바로 보여줄 수 있습니다.

## 무엇을 보여주는가

1. **하나의 코드, 개발자별 에이전트** — `SKILL.md` 파일 하나가 에이전트의 행동(형식, 저장소, 트리아지 규칙)을 결정. Python 코드 변경 없이 새 개발자 추가.
2. **로컬에서 만들고, 원격으로 배포** — `local-agent/chat.py`로 터미널에서 테스트 → `managed-agentcore/deploy.py`로 팀 서비스화. 에이전트 로직은 동일.
3. **하나의 런타임, 전체 팀 지원** — AgentCore Runtime 하나에 `dev_name`을 바꿔 요청하면 각 개발자의 SKILL.md가 로드됨.

## 핵심 기술 기능

| 기능 | 설명 |
|------|------|
| **SKILL.md 개인화** | 개발자별 형식, 담당 저장소, PR 트리아지 규칙을 마크다운으로 정의. `{skill_dir}` 플레이스홀더로 스크립트 경로 포터블. |
| **Prompt Caching** | 시스템 프롬프트 + Active Skill (~4,877 토큰)을 Bedrock 캐시에 올려 Turn 2+에서 재사용. 4턴 세션 기준 ~52% 비용 절감. |
| **멀티턴 세션** | 로컬: 같은 Agent 객체 재사용. AgentCore: `runtimeSessionId`로 같은 microVM 라우팅 → `agent.messages` 보존. |
| **크로스 세션 메모리** | AgentCore Memory로 이전 대화의 사실을 시맨틱 검색. "어제 말씀하신 블로커는 해결되셨나요?" |
| **SSE 스트리밍** | AgentCore Runtime에서 `yield`로 실시간 텍스트 전달. 클라이언트가 토큰 단위로 수신. |
| **SlidingWindow** | `window_size=20`으로 대화 길어져도 토큰 안정 (3,000-4,000/턴). 캐시 패턴 유지. |

---

## 빠른 시작

```bash
bash setup.sh                        # 의존성 설치, .env 생성, GitHub 토큰 설정
uv run local-agent/chat.py           # 대화형 채팅 (로컬)
```

## 로컬 채팅

```bash
uv run local-agent/chat.py                       # 기본값: sejong
uv run local-agent/chat.py --dev_name sunshin     # 개발자 지정
uv run local-agent/chat.py --date 2026-04-06      # 날짜 시뮬레이션 (데모용)
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

## GitHub 토큰

`github_standup.py`는 토큰을 SSM Parameter Store에서 먼저 조회하고, 실패 시 `.env`의 `GITHUB_TOKEN`으로 폴백합니다.

```bash
bash setup/store_github_token.sh     # SSM에 SecureString으로 저장 (권장)
```

수동 설정이 필요하면 IAM에 `ssm:GetParameter`, `ssm:PutParameter`, `kms:Decrypt` 권한이 필요합니다.

## 문서

| 폴더 | 내용 |
|------|------|
| [`docs/architecture/`](docs/architecture/) | 기술 아키텍처 — 로컬 vs AgentCore 비교, 프롬프트 캐싱, 메모리 구조, 토큰 흐름 |
| [`docs/demo/`](docs/demo/) | 데모 스크립트, 데모 컨셉 |
| [`docs/history/`](docs/history/) | 설계 스펙, 구현 계획, 실험 기록 |
