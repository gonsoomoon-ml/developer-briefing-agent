# 아키텍처: 에이전트가 스킬을 호출할 때의 토큰 흐름

## 개요

에이전트 실행 시, 개발자의 `SKILL.md`를 시스템 프롬프트에 직접 인라인(static loading)하고,
도구 호출을 자율적으로 연쇄하여 GitHub 데이터를 수집하고 스탠드업을 생성합니다.
GitHub 토큰은 데이터 수집 스크립트 내부에서만 사용되며, 에이전트의 프로세스 환경에는 노출되지 않습니다.

## 흐름 다이어그램

```
┌──────────────────────────────────────────────────────────────────────┐
│  User: uv run local-agent/chat.py                                    │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  chat.py → create_agent(dev_name)                                    │
│                                                                      │
│  load_dotenv()  ← .env (DEV_NAME=sejong, STRANDS_NON_INTERACTIVE)   │
│                    ⚠ GITHUB_TOKEN은 여기서 불필요                     │
│                                                                      │
│  system_prompt.md + skills/{dev_name}/SKILL.md → 결합                │
│                                                                      │
│  Agent(                                                              │
│    model = BedrockModel("global.anthropic.claude-sonnet-4-6")        │
│    tools = [shell, file_read]                                        │
│    system_prompt = [SystemContentBlock(text=...), cachePoint]        │
│  )                                                                   │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
          ┌────────────┼─── 에이전트가 자율적으로 도구 호출 결정 ───┐
          │            │                                            │
          ▼            ▼                                            ▼
   ┌─────────┐  ┌───────────┐                              ┌────────────┐
   │ SKILL.md│  │   shell   │                              │ file_read  │
   │ (인라인)│  │  (step 1) │                              │  (step 2)  │
   └────┬────┘  └─────┬─────┘                              └─────┬──────┘
        │             │                                          │
        ▼             ▼                                          ▼
┌──────────────┐  ┌──────────────────────────────────┐  ┌───────────────────┐
│  SKILL.md    │  │  github_standup.py               │  │ /tmp/standup_data │
│              │  │                                  │  │     .json         │
│ - 형식 규칙  │  │  get_github_token()              │  │                   │
│ - 담당 저장소│  │    │                             │  │ { commits, PRs }  │
│ - 스크립트   │  │    ├─ 1. SSM 조회 ─────────┐    │  └───────────────────┘
└──────────────┘  │    │                       │    │
                  │    │                       ▼    │
                  │    │  ┌─────────────────────┐   │
                  │    │  │ AWS SSM Parameter   │   │
                  │    │  │ Store (SecureString) │   │
                  │    │  │                     │   │
                  │    │  │ /developer-briefing │   │
                  │    │  │ -agent/github-token │   │
                  │    │  └──────────┬──────────┘   │
                  │    │             │              │
                  │    │     성공    │ 실패         │
                  │    │         ┌───┘    │         │
                  │    │         │        ▼         │
                  │    │         │  2. 폴백:        │
                  │    │         │  os.environ      │
                  │    │         │  ["GITHUB_TOKEN"] │
                  │    │         │  (.env에서)       │
                  │    │         │        │         │
                  │    │         ▼        ▼         │
                  │    │      토큰 확보             │
                  │    │         │                  │
                  │    │         ▼                  │
                  │    │  ┌─────────────────┐       │
                  │    │  │ GitHub REST API │       │
                  │    │  │ api.github.com  │       │
                  │    │  │                 │       │
                  │    │  │ • /user         │       │
                  │    │  │ • /repos/commits│       │
                  │    │  │ • /repos/pulls  │       │
                  │    │  └────────┬────────┘       │
                  │    │           │                │
                  │    │           ▼                │
                  │    │  → /tmp/standup_data.json  │
                  │    │                            │
                  └────┼────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LLM이 스탠드업 생성:                                                │
│    • SKILL.md 형식 규칙 (3 bullets / 번호 목록)                      │
│    • JSON 데이터 (커밋, PR, 오픈 리뷰)                               │
│                                                                      │
│  ✅ GITHUB_TOKEN이 에이전트의 os.environ에 없음 (SSM 사용 시)        │
│  ✅ LLM이 `env` 명령을 실행해도 민감 정보 노출 없음                   │
└──────────────────────────────────────────────────────────────────────┘
```

## 보안 경계

핵심 보안 속성: `github_standup.py`는 `shell` 도구를 통해 **자식 프로세스**로 실행됩니다.
토큰은 그 프로세스 내에서만 조회하고 사용합니다. 에이전트의 환경(LLM이 introspection 가능한 영역)으로 흘러나오지 않습니다.

| 경로 | 에이전트 환경에 토큰? | LLM에 토큰 노출? |
|------|---------------------|-------------------|
| SSM 사용 중 | 없음 | 없음 |
| SSM 불가, `.env` 폴백 | 있음 | 가능 (`env` 명령 등) |

## 토큰 조회 순서

```
get_github_token()
  │
  ├─ try: import boto3
  │   └─ ImportError → os.environ으로 폴백
  │
  ├─ try: ssm.get_parameter("/developer-briefing-agent/github-token")
  │   └─ 성공 → 토큰 반환 (os.environ 미접촉)
  │   └─ 실패 → os.environ으로 폴백
  │
  └─ os.environ.get("GITHUB_TOKEN")
      └─ None → 에러 출력 후 종료
```
