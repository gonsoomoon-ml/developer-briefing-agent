# 에이전트 실행 흐름 — 프롬프트, 도구, 보안

## 개요

에이전트 실행 시, 개발자의 `SKILL.md`를 시스템 프롬프트에 직접 인라인(static loading)하고,
도구 호출을 자율적으로 연쇄하여 GitHub 데이터를 수집하고 스탠드업을 생성합니다.

`--debug` 플래그로 실행하면 매 LLM 호출마다 전체 프롬프트를 확인할 수 있습니다.

```bash
uv run local-agent/chat.py --date 2026-04-07 --debug
```

## 전체 실행 흐름 다이어그램

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
└──────────────────────────────────────────────────────────────────────┘
```

## LLM 호출 흐름 (한 턴에 여러 번 호출)

사용자가 "어제 뭐 했어?"를 입력하면 다음 순서로 진행됩니다:

```
사용자 입력: "어제 뭐 했어?"
    │
    ├─ [Hook] BeforeInvocationEvent
    │   └─ retrieve_context(): AgentCore Memory에서 과거 사실 검색
    │       → 5건의 사실을 [이전 대화에서 알게 된 정보]로 사용자 메시지에 주입
    │
    ├─ [LLM 호출 1] 사용자 질문 + 메모리 컨텍스트 → 어떤 도구를 쓸지 판단
    │   └─ 응답: shell(github_standup.py) 호출 결정
    │
    ├─ [도구 실행] shell → github_standup.py 실행, /tmp/standup_data.json 생성
    │
    ├─ [LLM 호출 2] 이전 대화 + 도구 결과 → 다음 도구 판단
    │   └─ 응답: file_read(/tmp/standup_data.json) 호출 결정
    │
    ├─ [도구 실행] file_read → JSON 데이터 반환
    │
    ├─ [LLM 호출 3] 이전 대화 + 모든 도구 결과 → 최종 응답 생성
    │   └─ 응답: 메모리 컨텍스트 + GitHub 데이터를 종합하여 브리핑 생성
    │
    └─ [Hook] AfterInvocationEvent
        └─ save_interaction(): 사용자 질문 + 최종 응답을 AgentCore Memory에 저장
```

## LLM에 전달되는 메시지 구조

### LLM 호출 1 (첫 번째 호출)

```
[SYSTEM]
당신은 sejong의 일일 스탠드업 어시스턴트입니다.
모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요.
오늘은 2026-04-07 화요일입니다.

## Active Skill
(SKILL.md 내용이 여기에 inline)

[0 USER]
[이전 대화에서 알게 된 정보]                    ← AgentCore Memory에서 검색된 과거 사실
- developer-briefing-agent 프로젝트 구조 개편 및 한국어 리팩토링 완료 (2026-04-05)
- 사용자 이름: sejong
- 개발자 이름 변경: alex→sejong, maria→sunshin
- SSM Parameter Store에서 GitHub 토큰 연동 구현 (2026-04-05)
- 2026-04-06 기준 오픈 PR 없음

위 정보를 참고하되, 현재 질문에 관련된 내용만 활용하세요.

어제 뭐 했어?                                   ← 실제 사용자 질문
```

### LLM 호출 2 (shell 결과 포함)

```
[SYSTEM] (동일)
[0 USER] (동일 — 메모리 컨텍스트 + 사용자 질문)

[1 ASSISTANT]
GitHub 데이터를 수집하고 있어요!
🔧 shell({command: python github_standup.py --repos ... --output /tmp/standup_data.json})

[2 USER]                                         ← 도구 실행 결과
📋 Command: python github_standup.py ...
Status: success
```

### LLM 호출 3 (file_read 결과 → 최종 응답)

```
[SYSTEM] (동일)
[0 USER] ~ [2 USER] (이전 대화 전체)

[3 ASSISTANT]
🔧 file_read({file_path: /tmp/standup_data.json})

[4 USER]                                         ← JSON 데이터
📋 {
  "username": "gonsoomoon-ml",
  "since": "2026-04-02",
  "repos": {
    "gonsoomoon-ml/developer-briefing-agent": {
      "commits": [
        {"sha": "b156e05", "message": "feat: 프로젝트 구조 개편...", "date": "2026-04-05"},
        ...
      ],
      "open_prs": []
    }
  }
}

→ LLM이 모든 정보를 종합하여 최종 브리핑 생성
```

## 컨텍스트 구성 요소

| 구성 요소 | 출처 | 언제 주입되는가 |
|-----------|------|----------------|
| 시스템 프롬프트 | `create_agent()` | 에이전트 생성 시 |
| `--date` 날짜 정보 | 시스템 프롬프트에 추가 | 에이전트 생성 시 |
| Active Skill (SKILL.md) | 시스템 프롬프트에 inline | 에이전트 생성 시 |
| `[이전 대화에서 알게 된 정보]` | AgentCore Memory (LTM) | `BeforeInvocationEvent` 훅 (첫 턴만) |
| 사용자 질문 | 사용자 입력 | `agent.stream_async(prompt)` 호출 시 |
| GitHub 데이터 (JSON) | `shell` → `file_read` 도구 결과 | LLM이 도구 호출 후 |
| 이전 턴 대화 (인세션) | `agent.messages` | 자동 누적 |

## 보안 경계

핵심 보안 속성: `github_standup.py`는 `shell` 도구를 통해 **자식 프로세스**로 실행됩니다.
토큰은 그 프로세스 내에서만 조회하고 사용합니다. 에이전트의 환경(LLM이 introspection 가능한 영역)으로 흘러나오지 않습니다.

| 경로 | 에이전트 환경에 토큰? | LLM에 토큰 노출? |
|------|---------------------|-------------------|
| SSM 사용 중 | 없음 | 없음 |
| SSM 불가, `.env` 폴백 | 있음 | 가능 (`env` 명령 등) |

### GitHub 토큰 조회 순서

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

## 디버그 출력 가이드

`--debug` 플래그 활성화 시 아래 디버그 메시지가 출력됩니다:

| 디버그 메시지 | 의미 |
|--------------|------|
| `🔍 retrieve_context` | AgentCore Memory에서 과거 사실 검색 및 주입 |
| `⏭ retrieve_context` | 첫 턴 아님 — 검색 건너뜀 (agent.messages가 처리) |
| `📝 FULL PROMPT TO LLM` | 매 LLM 호출 직전 전체 프롬프트 덤프 |
| `💾 save_interaction` | 턴 종료 후 사용자+어시스턴트 쌍을 AgentCore에 저장 |
| `❌` | 오류 발생 시 |
