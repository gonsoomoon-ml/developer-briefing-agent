# Developer Briefing Agent Demo

**Strands Agents SDK** + **Amazon Bedrock AgentCore Runtime** 5분 데모

> "오후 반나절이면 에이전트를 만들 수 있습니다. 한 번 배포하면 팀 전체가 사용합니다."

## 핵심 메시지

동일한 코드, 다른 `SKILL.md` → 완전히 다른 출력

```
local-agent/strands_agent.py  (20줄)     managed-agentcore/agentcore_runtime.py  (35줄)
      │                                        │
      ├── tools=[shell, file_read]             └── @app.entrypoint + async streaming
      └── plugins=[AgentSkills(...)]               BedrockAgentCoreApp()
```

## 빠른 시작

```bash
bash setup.sh                        # 의존성 설치, .env 생성, GitHub 토큰 설정
uv run local-agent/chat.py           # 대화형 채팅 (로컬)
```

## 프로젝트 구조

```
local-agent/                          # 로컬 에이전트
  strands_agent.py                    # Strands Agent — 20줄
  chat.py                             # 대화형 터미널 채팅
  .env.example                        # GITHUB_TOKEN, DEV_NAME

managed-agentcore/                    # AgentCore Runtime 배포
  agentcore_runtime.py                # @app.entrypoint — 스트리밍 지원
  01_create_agentcore_runtime.py      # 빌드 + 배포 (Docker → ECR → Runtime)
  02_invoke_agentcore_runtime.py      # 단일 호출 테스트
  chat.py                             # 대화형 터미널 채팅 (원격)
  requirements.txt                    # 컨테이너 의존성
  .env.example                        # RUNTIME_ARN, AWS_REGION

shared/                               # 공유 모듈
  memory_hooks.py                     # StandupMemoryHooks — 크로스 세션 메모리

skills/                               # 개발자별 스킬 (소스)
  sejong/
    SKILL.md                          # 3 bullets, 블로커 우선
    scripts/github_standup.py         # GitHub 데이터 수집 CLI
  sunshin/
    SKILL.md                          # numbered list, 상세 설명
    scripts/github_standup.py

setup.sh                              # 원커맨드 셋업
setup/
  store_github_token.sh               # SSM Parameter Store에 토큰 저장
  create_memory.py                    # AgentCore Memory 리소스 생성
docs/
```

## 시연 기능

| Strands Agents SDK | Amazon Bedrock AgentCore |
|--------------------|--------------------------|
| `AgentSkills` + `SKILL.md` — 코드 변경 없이 개발자별 개인화 | Runtime — 에이전트를 팀 서비스로 호스팅 |
| `shell` + `file_read` — 스킬 내 CLI 스크립트 실행 | SSE 스트리밍 — 실시간 응답 |
| 대화형 채팅 — 컨텍스트 유지, `/switch`로 개발자 전환 | `dev_name` per-request — 하나의 런타임으로 전체 팀 지원 |
| Hooks — `BeforeInvocation`/`AfterInvocation` 자동 메모리 | Memory — 크로스 세션 시맨틱 메모리 |

## 5분 데모 흐름

| 시간 | 내용 |
|------|------|
| 0–1분 | `local-agent/strands_agent.py` — 20줄이 전부 |
| 1–2분 | `skills/sejong/SKILL.md` — Sejong의 형식과 담당 저장소 |
| 2–3분 | `uv run local-agent/chat.py` — Sejong 브리핑 + 후속 질문 |
| 3–4분 | `/switch sunshin` → 동일한 코드, 완전히 다른 출력 |
| 4–5분 | `managed-agentcore/agentcore_runtime.py` → 배포 → `chat.py`로 원격 호출 |

## 로컬 채팅

```bash
# Sejong으로 시작
uv run local-agent/chat.py

# Sunshin으로 시작
uv run local-agent/chat.py --dev_name sunshin
```

| 명령 | 설명 |
|------|------|
| `/switch <name>` | 개발자 전환 (예: `/switch sunshin`) |
| `/quit` | 종료 |

유용한 프롬프트:

| 프롬프트 | 설명 |
|---------|------|
| 오늘 업무 브리핑 해줘 | 전체 스탠드업 브리핑 |
| 리뷰할 PR 있어? | 오픈 PR 확인 |
| 이번 주 뭐 했는지 알려줘 | 주간 활동 요약 |

## AgentCore Runtime 배포

```bash
# 배포 (Docker 빌드 → ECR 푸시 → Runtime 생성, ~5분)
uv run managed-agentcore/01_create_agentcore_runtime.py

# 단일 호출 테스트
uv run managed-agentcore/02_invoke_agentcore_runtime.py
uv run managed-agentcore/02_invoke_agentcore_runtime.py --dev_name sunshin

# 대화형 채팅 (원격)
uv run managed-agentcore/chat.py
```

하나의 런타임으로 모든 개발자 지원 — `dev_name`을 payload로 전달하면 해당 개발자의 `SKILL.md`가 로드됩니다.

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
| `RUNTIME_ARN` | AgentCore Runtime ARN (01_create가 자동 설정) |
| `MEMORY_ID` | AgentCore Memory ID (선택, `create_memory.py`가 자동 설정) |

## 크로스 세션 메모리 (AgentCore Memory)

에이전트가 이전 대화를 기억하도록 설정할 수 있습니다 (선택 사항).

```bash
# 메모리 리소스 생성 (한 번만 실행)
uv run setup/create_memory.py
```

`MEMORY_ID`가 설정되면:
- 매 호출 전에 관련 과거 컨텍스트를 시맨틱 검색으로 조회
- 매 호출 후에 대화 내용을 자동 저장
- AgentCore가 백그라운드에서 사실을 추출 (~1분), 다음 세션에서 활용 가능

### 데모용 날짜 시뮬레이션

`--date` 플래그로 여러 날을 한 번에 시뮬레이션할 수 있습니다:

```bash
uv run local-agent/chat.py --date 2026-04-06    # "월요일"
# 브리핑 → /quit

uv run local-agent/chat.py --date 2026-04-07    # "화요일"
# "어제 이후로 뭐 바뀌었어?" → 월요일 내용을 기억하고 답변

uv run local-agent/chat.py --date 2026-04-10    # "금요일"
# "이번 주 요약해줘" → 누적된 컨텍스트로 주간 요약 생성
```

`MEMORY_ID`가 없으면 기존과 동일하게 무상태로 동작합니다.

## GitHub 토큰 보안 (SSM Parameter Store)

`github_standup.py`는 GitHub 토큰을 AWS SSM Parameter Store에서 먼저 조회합니다.
SSM을 사용할 수 없으면 `.env`의 `GITHUB_TOKEN`으로 폴백합니다.

### 설정 스크립트 (권장)

```bash
bash setup/store_github_token.sh
```

스크립트가 수행하는 단계:
1. AWS 자격 증명 확인 (`sts:GetCallerIdentity`)
2. SSM 관련 IAM 권한 확인 (`ssm:GetParameter`, `kms:Decrypt`)
3. GitHub 토큰 입력 (또는 `--token ghp_xxx` 인자로 전달)
4. SSM Parameter Store에 SecureString으로 저장
5. 읽기 검증 + GitHub API 인증 테스트

### 수동 설정

AWS CLI가 설치 및 구성되어 있어야 합니다:

```bash
aws configure   # Access Key, Secret Key, Region 입력
```

IAM 사용자/역할에 아래 권한이 필요합니다:
- `ssm:GetParameter`
- `ssm:PutParameter`
- `kms:Decrypt` (SecureString 복호화)

```bash
aws ssm put-parameter \
  --name "/developer-briefing-agent/github-token" \
  --type SecureString \
  --value "ghp_your_token"
```

두 가지 방법을 동시에 사용할 수 있습니다. SSM이 우선 조회되고, 실패 시 `.env`로 폴백합니다.

## 개발자 대비표

| | **Sejong** | **Sunshin** |
|---|---|---|
| 형식 | 3 bullets | Numbered list |
| 상세도 | bullet당 15단어 이하 | 항목당 2문장 |
| 저장소 | analyze-claude-code, developer-briefing-agent | sample-deep-insight, claude-extensions |
| PR 링크 | 없음 | 항상 포함 |
| 블로커 위치 | 있으면 맨 앞 | 항상 "What I need" 아래 |
