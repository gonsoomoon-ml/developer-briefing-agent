# Developer Briefing Agent Demo

**Strands Agents SDK** + **Amazon Bedrock AgentCore Runtime** 5분 데모

> "오후 반나절이면 에이전트를 만들 수 있습니다. 한 번 배포하면 팀 전체가 사용합니다."

## 핵심 메시지

동일한 코드, 다른 `SKILL.md` → 완전히 다른 출력

```
src/strands_agent.py  (20줄)       src/agentcore_runtime.py  (12줄)
      │                                        │
      ├── tools=[shell, file_read]             └── from strands_agent import agent
      └── plugins=[AgentSkills(...)]               app = BedrockAgentCoreApp()
```

## 빠른 시작

```bash
uv sync
cp .env.example .env   # GITHUB_TOKEN, DEV_NAME 입력
uv run src/strands_agent.py
```

## 프로젝트 구조

```
src/
  strands_agent.py        # Strands 에이전트 — 로컬 실행
  agentcore_runtime.py    # AgentCore 래퍼 — 프로덕션 배포
skills/
  sejong/
    SKILL.md              # Sejong의 형식: 3 bullets, 블로커 우선
    scripts/
      github_standup.py   # GitHub 데이터 수집 CLI
  sunshin/
    SKILL.md              # Sunshin의 형식: numbered list, 상세 설명
    scripts/
      github_standup.py   # GitHub 데이터 수집 CLI
docs/
  biz-requirement.md
  demo-idea.md
  specs/
    2026-04-03-strands-briefing-agent-design.md
```

## 시연 기능

| Strands Agents SDK | Amazon Bedrock AgentCore |
|--------------------|--------------------------|
| `AgentSkills` + `SKILL.md` — 코드 변경 없이 개발자별 개인화 | Runtime — 에이전트를 팀 서비스로 호스팅 |
| `shell` + `file_read` — 스킬 내 CLI 스크립트 실행 | |

## 5분 데모 흐름

| 시간 | 내용 |
|------|------|
| 0–1분 | `src/strands_agent.py` — 20줄이 전부 |
| 1–2분 | `skills/sejong/SKILL.md` + `scripts/github_standup.py` — Sejong의 형식과 데이터 수집 |
| 2–3분 | Sejong으로 실행 → 실제 GitHub 활동 기반 브리핑 출력 |
| 3–3:30 | `skills/sunshin/SKILL.md` — 다른 형식, 다른 저장소 |
| 3:30–4분 | Sunshin으로 실행 → 동일한 코드, 완전히 다른 출력 |
| 4–5분 | `src/agentcore_runtime.py` 공개 → `bedrock-agentcore launch` 한 줄로 팀 서비스 배포 |

## AgentCore Runtime 배포

`.bedrock_agentcore.yaml`은 SDK가 자동 생성합니다.

```bash
bedrock-agentcore launch --agent standup_agent

bedrock-agentcore invoke --agent standup_agent \
  --payload '{"prompt": "Write my standup for today"}' \
  --env DEV_NAME=sejong GITHUB_TOKEN=$GITHUB_TOKEN
```

## 환경 변수

| 변수 | 설명 |
|------|------|
| `GITHUB_TOKEN` | GitHub PAT (`repo` + `read:user` 권한) — SSM Parameter Store 또는 `.env` 둘 다 지원 |
| `DEV_NAME` | 개발자 이름 — `sejong` 또는 `sunshin` |
| `STRANDS_NON_INTERACTIVE` | `true` — shell 툴 확인 프롬프트 비활성화 |

## GitHub 토큰 보안 (SSM Parameter Store)

`github_standup.py`는 GitHub 토큰을 AWS SSM Parameter Store에서 먼저 조회합니다.
SSM을 사용할 수 없으면 `.env`의 `GITHUB_TOKEN`으로 폴백합니다.

### 설정 스크립트 (권장)

설정 스크립트가 AWS 권한 확인, 토큰 저장, 검증을 모두 처리합니다:

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

두 가지 방법을 동시에 ��용할 수 있습니다. SSM이 우선 조회되고, 실패 시 `.env`로 폴백합니다.
