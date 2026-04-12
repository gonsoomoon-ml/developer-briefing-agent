# 데모 스크립트 & 채팅 명령어

## 채팅 명령어

```bash
# 채팅 시작 (기본값: sejong)
uv run local-agent/chat.py

# 개발자 지정
uv run local-agent/chat.py --dev_name sunshin
```

| 명령 | 설명 |
|------|------|
| `/switch <name>` | 개발자 전환 (예: `/switch sunshin`) |
| `/quit` 또는 `quit` | 종료 |

## 유용한 프롬프트

| 프롬프트 | 설명 |
|---------|------|
| 오늘 업무 브리핑 해줘 | 전체 스탠드업 브리핑 |
| 리뷰할 PR 있어? | 오픈 PR 확인 |
| 이번 주 뭐 했는지 알려줘 | 주간 활동 요약 |
| 오늘 할 일 알려줘 | 오늘의 작업 목록 |

## 5분 데모 흐름

### Act 1: 에이전트 (0–1분)

`local-agent/example_single_shot.py` 열기:
- 에이전트 전체 코드
- `Agent(tools=[shell, file_read], system_prompt=[...])` — 도구 2개와 시스템 프롬프트
- "에이전트 전체가 이 파일 하나입니다"

### Act 2: 개인화 (1–2분)

`skills/sejong/SKILL.md` 열기:
- 형식: 3 bullets, 블로커 우선
- 담당 저장소: analyze-claude-code, developer-briefing-agent
- "코드 변경 없이 마크다운 파일 하나가 행동을 결정합니다"

### Act 3: Sejong 실행 (2–3분)

```
$ uv run local-agent/chat.py

==================================================
  개발자 브리핑 에이전트 (sejong)
==================================================

> 오늘 업무 브리핑 해줘

(스트리밍 출력 — 3 bullets, 블로커 우선, 간결)

> 리뷰할 PR 있어?

(대화 컨텍스트 유지 — 데이터 재수집 없이 답변)
```

핵심 메시지: "동일한 코드, 스트리밍 출력, 대화 컨텍스트 유지"

### Act 4: Sunshin 전환 (3–4분)

`skills/sunshin/SKILL.md` 보여주기:
- 형식: 번호 목록 (What I shipped / What I'm building / What I need)
- 다른 저장소: sample-deep-insight, claude-extensions
- "다른 마크다운 파일, 완전히 다른 출력"

```
> /switch sunshin
sunshin(으)로 전환했습니다

> 순신의 업무 브리핑 해줘

(스트리밍 출력 — 번호 목록, 상세, PR 링크 포함)

> 리뷰할 PR 있어?

(PR #45 클릭 가능한 링크 표시 — Sejong에는 없었음)
```

핵심 메시지: "코드 변경 제로. 같은 에이전트, 다른 SKILL.md, 완전히 다른 행동"

### Act 5: 팀 서비스로 배포 (4–5분)

`managed-agentcore/agentcore_runtime.py` 보여주기:
- 같은 에이전트를 `@app.entrypoint`로 래핑
- `dev_name` per-request — 하나의 런타임으로 전체 팀 지원

```bash
# 배포 (데모 전에 완료 — ~5분 소요)
uv run managed-agentcore/deploy.py

# 팀 서비스로 호출
uv run managed-agentcore/example_invoke.py
uv run managed-agentcore/example_invoke.py --dev_name sunshin
```

핵심 메시지: "한 번 배포하면 팀 전체가 사용합니다"
