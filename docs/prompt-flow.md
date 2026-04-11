# 프롬프트 흐름 — LLM에 전달되는 전체 컨텍스트

`--debug` 플래그로 실행하면 매 LLM 호출마다 전체 프롬프트를 확인할 수 있습니다.

```bash
uv run local-agent/chat.py --date 2026-04-07 --debug
```

## 호출 흐름 (한 턴에 LLM이 여러 번 호출됨)

사용자가 "어제 뭐 했어?"를 입력하면 다음 순서로 진행됩니다:

```
사용자 입력: "어제 뭐 했어?"
    │
    ├─ [Hook] BeforeInvocationEvent
    │   └─ retrieve_context(): AgentCore Memory에서 과거 사실 검색
    │       → 5건의 사실을 [이전 대화에서 알게 된 정보]로 사용자 메시지에 주입
    │
    ├─ [LLM 호출 1] 사용자 질문 + 메모리 컨텍스트 → 어떤 도구를 쓸지 판단
    │   └─ 응답: skills(sejong) + shell(date) 호출 결정
    │
    ├─ [도구 실행] skills → SKILL.md 반환, shell(date) → 현재 시각 반환
    │
    ├─ [LLM 호출 2] 이전 대화 + 도구 결과 → 다음 도구 판단
    │   └─ 응답: shell(github_standup.py) 호출 결정
    │
    ├─ [도구 실행] shell → github_standup.py 실행, /tmp/standup_data.json 생성
    │
    ├─ [LLM 호출 3] 이전 대화 + 도구 결과 → 다음 도구 판단
    │   └─ 응답: file_read(/tmp/standup_data.json) 호출 결정
    │
    ├─ [도구 실행] file_read → JSON 데이터 반환
    │
    ├─ [LLM 호출 4] 이전 대화 + 모든 도구 결과 → 최종 응답 생성
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

<available_skills>
  <skill>
    <name>sejong</name>
    <description>Daily standup for Sejong — GitHub activity based, 3 bullets format</description>
    <location>/home/ubuntu/developer-briefing-agent/skills/sejong/SKILL.md</location>
  </skill>
</available_skills>

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

### LLM 호출 2 (skills + date 도구 결과 포함)

```
[SYSTEM] (동일)

[0 USER] (동일 — 메모리 컨텍스트 + 사용자 질문)

[1 ASSISTANT]
스킬 정보를 불러오고 최신 GitHub 활동을 확인할게요!
🔧 skills({skill_name: sejong})
🔧 shell({command: date})

[2 USER]                                         ← 도구 실행 결과
📋 ## 담당 저장소
- gonsoomoon-ml/analyze-claude-code
- gonsoomoon-ml/developer-briefing-agent

## 스탠드업 형식
Format: 3 bullets max. 이번 주 한 일 / 오늘 할 일 / 블로커.
...

📋 Command: date
Output: Thu Apr  9 03:36:00 UTC 2026
```

### LLM 호출 3 (github_standup.py 실행 결과 포함)

```
[SYSTEM] (동일)
[0 USER] (동일)
[1 ASSISTANT] (동일)
[2 USER] (skills + date 결과)

[3 ASSISTANT]
GitHub 데이터를 수집하고 있어요!
🔧 shell({command: python github_standup.py --repos ... --output /tmp/standup_data.json})

[4 USER]                                         ← github_standup.py 실행 결과
📋 Command: python github_standup.py ...
Status: success
```

### LLM 호출 4 (file_read 결과 포함 → 최종 응답)

```
[SYSTEM] (동일)
[0 USER] (동일)
[1 ASSISTANT] ~ [4 USER] (이전 대화 전체)

[5 ASSISTANT]
🔧 file_read({file_path: /tmp/standup_data.json})

[6 USER]                                         ← JSON 데이터
📋 {
  "username": "gonsoomoon-ml",
  "since": "2026-04-02",
  "repos": {
    "gonsoomoon-ml/analyze-claude-code": {
      "commits": [],
      "open_prs": []
    },
    "gonsoomoon-ml/developer-briefing-agent": {
      "commits": [
        {"sha": "b156e05", "message": "feat: 프로젝트 구조 개편...", "date": "2026-04-05"},
        {"sha": "996cf11", "message": "feat: rename developers...", "date": "2026-04-05"},
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
| `<available_skills>` | `AgentSkills` 플러그인 | 에이전트 생성 시 |
| `[이전 대화에서 알게 된 정보]` | AgentCore Memory (LTM) | `BeforeInvocationEvent` 훅 (첫 턴만) |
| 사용자 질문 | 사용자 입력 | `agent.stream_async(prompt)` 호출 시 |
| SKILL.md 내용 | `skills` 도구 결과 | LLM이 도구 호출 후 |
| GitHub 데이터 (JSON) | `shell` → `file_read` 도구 결과 | LLM이 도구 호출 후 |
| 이전 턴 대화 (인세션) | `agent.messages` | 자동 누적 |

## 메모리 관련 디버그 출력

`--debug` 플래그 활성화 시 아래 디버그 메시지가 출력됩니다:

| 디버그 메시지 | 의미 |
|--------------|------|
| `🔍 retrieve_context` | AgentCore Memory에서 과거 사실 검색 및 주입 |
| `⏭ retrieve_context` | 첫 턴 아님 — 검색 건너뜀 (agent.messages가 처리) |
| `📝 FULL PROMPT TO LLM` | 매 LLM 호출 직전 전체 프롬프트 덤프 |
| `💾 save_interaction` | 턴 종료 후 사용자+어시스턴트 쌍을 AgentCore에 저장 |
| `❌` | 오류 발생 시 |
