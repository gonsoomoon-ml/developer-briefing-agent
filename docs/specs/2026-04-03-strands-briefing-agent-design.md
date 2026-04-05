# 데모 설계: "내 스탠드업 작성해줘" 에이전트

**날짜:** 2026-04-03
**데모 시간:** 5분
**대상:** 개발자

---

## 핵심 개념

개발자 한 명 한 명이 한 번만 배포하고, 매일 아침 메시지를 보내면 스탠드업을 대신 작성해주는 개인 에이전트.

**핵심 메시지:**
> "오후 반나절이면 에이전트를 만들 수 있습니다. 한 번 배포하면 팀 전체가 사용합니다."

---

## 시연 기능

### Strands Agents SDK
| 기능 | 데모에서의 역할 |
|---|---|
| `http_request` 커뮤니티 툴 | 에이전트가 GitHub API를 자율적으로 호출 — 개발자가 REST 로직을 직접 작성하지 않아도 됨 |
| `AgentSkills` + `SKILL.md` | 코드 변경 없이 개발자별 마크다운 파일로 개인화 |

### Amazon Bedrock AgentCore
| 기능 | 데모에서의 역할 |
|---|---|
| Runtime | 에이전트를 채팅으로 호출 가능한 팀 서비스로 호스팅 |

---

## 5분 데모 흐름

| 시간 | 청중이 보는 것 |
|---|---|
| 0:00–1:00 | `strands_agent.py` 화면 — `Agent(tools=[http_request], plugins=[AgentSkills(...)])`. 총 약 20줄 |
| 1:00–2:00 | `alex/SKILL.md` — Alex의 스탠드업 형식과 우선순위를 정의한 평문 마크다운 |
| 2:00–3:00 | 로컬 실행 → 에이전트가 GitHub를 호출하고 터미널에 스탠드업 출력 |
| 3:00–3:30 | `maria/SKILL.md` 공개 — 다른 형식, 다른 우선순위 |
| 3:30–4:00 | Maria로 실행 → 동일한 코드, 다른 출력 결과 |
| 4:00–5:00 | `agentcore_runtime.py` 공개 — `strands_agent.py`를 감싸는 12줄. `bedrock-agentcore launch` 한 줄로 배포 → 이제는 팀 서비스 |

### "아하!" 순간
- **2분:** 에이전트가 어떤 GitHub 엔드포인트를 호출할지 스스로 판단 — 개발자가 REST 로직을 한 줄도 작성하지 않음
- **3분 30초:** 동일한 코드, 완전히 다른 출력 — Skills가 해낸 것
- **4분 30초:** 로컬 스크립트 → 팀 서비스, 12줄 래퍼 하나

---

## 코드 구조

### `strands_agent.py` (로컬 실행 — 데모 핵심)
```python
import os
from dotenv import load_dotenv
from strands import Agent, AgentSkills
from strands_tools import http_request
from strands.models import BedrockModel

load_dotenv()  # 로컬 전용 — AgentCore Runtime에서는 no-op

dev_name = os.environ.get("DEV_NAME", "alex")

agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
    system_prompt=(
        f"You are a daily standup assistant for {dev_name}. "
        f"Use GITHUB_TOKEN as Bearer token for https://api.github.com endpoints."
    ),
    tools=[http_request],
    plugins=[AgentSkills(skills=f"./skills/{dev_name}/")],
)

if __name__ == "__main__":
    response = agent("Write my standup for today")
    print(response)
```

### `agentcore_runtime.py` (프로덕션 배포 — strands_agent.py 래퍼)
```python
from strands_agent import agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
def standup_agent(payload):
    response = agent(payload.get("prompt", "Write my standup for today"))
    return response.message["content"][0]["text"]

if __name__ == "__main__":
    app.run()
```

### 프로젝트 구조
```
26_demo_for_strand_agentcore/
  strands_agent.py      # Strands 에이전트 — 로컬 실행
  agentcore_runtime.py  # AgentCore 래퍼 — 프로덕션 배포
  pyproject.toml        # 프로젝트 루트 — uv run은 여기서 실행
  .env                  # 로컬 전용 (gitignore) — GITHUB_TOKEN, DEV_NAME
  .env.example          # 커밋 가능한 템플릿
  skills/
    alex/SKILL.md       # name: alex
    maria/SKILL.md      # name: maria
  tests/
    test_agent.py
  setup/
    create_env.sh       # uv sync 래퍼 스크립트
```

### 배포
```bash
bedrock-agentcore launch --agent standup_agent
```

---

## 의도적으로 제외한 것들

- **GitHub MCP / AgentCore Gateway** — OAuth/인프라 복잡도가 추가되어 "간단하다"는 메시지를 희석시킴
- **Slack 출력** — 웹훅 설정이 에이전트 코드보다 주목을 끌게 됨
- **스케줄 실행** — AgentCore Runtime은 채팅으로 호출하는 서비스이며, 크론 잡이 아님
- **메모리** — 5분 데모 범위 밖
- **다중 데이터 소스** (Jira, Calendar) — 하나의 소스에 집중해야 데모가 명확해짐

---

## 용어 정의

**스탠드업(Standup)**
매일 아침 팀이 짧게 모여 진행하는 일일 회의 (보통 15분 이내).
"서서 회의해서 짧게 끝내자"는 의미에서 유래. 세 가지 질문에 답하는 형식으로 진행:
1. 어제 한 일
2. 오늘 할 일
3. 블로커 (진행을 막는 문제)

개발자가 매일 아침 git log, PR 상태, 티켓을 직접 뒤져서 정리해야 하는 번거로운 작업 — 에이전트가 GitHub를 보고 자동으로 작성해줌.

---

## 이 유즈케이스를 선택한 이유

일반적인 "아침 브리핑" 대신 스탠드업 생성을 선택한 이유:
- 개발자가 매일 해야 하는 작업이며, 번거롭다고 느끼는 경우가 많음
- GitHub API에서 개인 액세스 토큰 하나로 필요한 데이터를 모두 가져올 수 있음
- 출력 결과가 짧고 즉시 검증 가능하며, 청중인 개발자 누구나 공감할 수 있음
- Skills 개인화가 자연스러움: 팀마다 스탠드업 형식이 다르기 때문
