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

## 데모 흐름 (비디오)

### Act 1: 에이전트 코드

`local-agent/example_single_shot.py` 열기:
- 에이전트 전체 코드
- `Agent(tools=[shell, file_read], system_prompt=[...])` — 도구 2개와 시스템 프롬프트
- "에이전트 전체가 이 파일 하나입니다"

바로 실행:
```
$ uv run local-agent/example_single_shot.py

(스트리밍 출력 — 한 번 실행 후 종료)
```

핵심 메시지: "이 파일 하나가 전부이고, 바로 실행됩니다"

### Act 2: 개인화

`skills/sejong/SKILL.md` 열기:
- 형식: 3 bullets, 블로커 우선
- 담당 저장소: analyze-claude-code, developer-briefing-agent
- "코드 변경 없이 마크다운 파일 하나가 행동을 결정합니다"

### Act 3: Sejong 실행

```
$ uv run local-agent/chat.py --dev_name sejong

==================================================
  개발자 브리핑 에이전트 (sejong)
==================================================

> 오늘 업무 브리핑 해줘

(스트리밍 출력 — 3 bullets, 블로커 우선, 간결)

> 리뷰할 PR 있어?

(대화 컨텍스트 유지 — 데이터 재수집 없이 답변)
```

핵심 메시지: "동일한 코드, 스트리밍 출력, 대화 컨텍스트 유지"

### Act 4: Sunshin 전환

`skills/sunshin/SKILL.md` 보여주기:
- 형식: 번호 목록 (What I shipped / What I'm building / What I need)
- 다른 저장소: aws-samples/sample-deep-insight, gonsoomoon-ml/claude-extensions
- dependabot PR 트리아지 규칙 — 위험 PR vs 일반 PR 자동 분류
- "다른 마크다운 파일, 완전히 다른 출력"

```
$ uv run local-agent/chat.py --dev_name sunshin

==================================================
  개발자 브리핑 에이전트 (sunshin)
==================================================

> 오늘 업무 브리핑 해줘

(스트리밍 출력 — 번호 목록, 상세, PR 링크 포함)

> 리뷰할 PR 있어?

(sample-deep-insight에 26개 오픈 PR — #48 사람 PR, #47 langchain-core major bump 등 트리아지 출력)
(Sejong에는 PR이 없었음 — 다른 저장소, 다른 규칙)
```

핵심 메시지: "코드 변경 제로. 같은 에이전트, 다른 SKILL.md, 완전히 다른 행동"

### Act 5: 크로스 세션 메모리

세션 종료 후 새 세션에서 이전 대화를 기억하는 것을 시연합니다.

**사전 준비:** `MEMORY_ID`가 `.env`에 설정되어 있어야 합니다 (`uv run setup/create_memory.py`).

```
# Act 4에서 sunshin으로 대화한 상태에서 종료
> /quit

--- (컷 편집) ---

# 새 세션 시작
$ uv run local-agent/chat.py --dev_name sunshin

==================================================
  개발자 브리핑 에이전트 (sunshin)
==================================================

> 아까 얘기한 PR 어떻게 됐어?

(이전 세션에서 논의한 PR 컨텍스트를 기억하고 답변)
```

핵심 메시지: "MEMORY_ID 환경변수 하나로 크로스 세션 메모리 활성화 — 코드 변경 없음"

**선택:** `--debug` 모드로 메모리 검색 과정을 시각적으로 보여줄 수도 있음:
```
$ uv run local-agent/chat.py --dev_name sunshin --debug

# 터미널에 [DEBUG 🔍 retrieve_context] 블록이 표시됨
# → 이전 세션에서 저장된 기억이 검색되는 과정 시각화
```

### Act 6: 팀 서비스로 배포

`managed-agentcore/agentcore_runtime.py` 보여주기:
- 같은 에이전트를 `@app.entrypoint`로 래핑
- `dev_name` per-request — 하나의 런타임으로 전체 팀 지원

```bash
# 배포 (데모 전에 완료 — ~5분 소요)
uv run managed-agentcore/deploy.py
```

```
# 팀 서비스로 호출 (원격 채팅)
$ uv run managed-agentcore/chat.py --dev_name sunshin

==================================================
  개발자 브리핑 에이전트 (sunshin)
  AgentCore Runtime 원격 호출
==================================================

> 오늘 업무 브리핑 해줘

(로컬과 동일한 출력 — 번호 목록, PR 트리아지 포함)

> 리뷰할 PR 있어?

(26개 PR 트리아지 — 로컬 chat.py와 동일한 결과)
```

핵심 메시지: "한 번 배포하면 팀 전체가 사용합니다"

## 스토리 아크 요약

```
Act 1 → Act 2 → Act 3 → Act 4 → Act 5 → Act 6
"쉽다"  "유연하다"  "된다"  "코드 변경 0"  "기억한다"  "확장된다"
```
