# AgentCore Memory Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent cross-session memory so the developer briefing agent remembers previous conversations per developer.

**Architecture:** A shared `StandupMemoryHooks` HookProvider retrieves relevant past context before each invocation and saves the interaction after. Both local and remote runtimes import it. A one-time setup script provisions the AgentCore memory resource.

**Tech Stack:** `bedrock_agentcore.memory.MemoryClient`, `strands.hooks.HookProvider`, `strands.hooks.events.BeforeInvocationEvent` / `AfterInvocationEvent`

---

### Task 1: Create shared memory hooks module

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/memory_hooks.py`

- [ ] **Step 1: Create `shared/__init__.py`**

Empty init file to make `shared/` importable as a package.

- [ ] **Step 2: Create `shared/memory_hooks.py`**

```python
"""
memory_hooks.py — AgentCore Memory 훅 프로바이더

에이전트 호출 전에 관련 기억을 검색하고, 호출 후에 대화를 저장합니다.

사용법:
    from shared.memory_hooks import StandupMemoryHooks
    hooks = [StandupMemoryHooks(memory_id, dev_name)]
    agent = Agent(..., hooks=hooks)
"""

import logging
import os

from bedrock_agentcore.memory import MemoryClient
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent, BeforeInvocationEvent

logger = logging.getLogger(__name__)


class StandupMemoryHooks(HookProvider):
    """개발자별 스탠드업 메모리 훅.

    BeforeInvocationEvent: 관련 기억을 검색하여 메시지에 주입
    AfterInvocationEvent: 대화를 이벤트로 저장
    """

    def __init__(self, memory_id: str, dev_name: str, region: str | None = None):
        self.memory_id = memory_id
        self.dev_name = dev_name
        self.client = MemoryClient(
            region_name=region or os.environ.get("AWS_REGION", "us-west-2")
        )

    def retrieve_context(self, event: BeforeInvocationEvent):
        """호출 전: 관련 기억을 검색하여 컨텍스트로 주입합니다."""
        try:
            messages = event.agent.messages
            if not messages or messages[-1]["role"] != "user":
                return

            # 마지막 사용자 메시지에서 쿼리 추출
            last_content = messages[-1].get("content", [])
            user_query = ""
            for block in last_content:
                if isinstance(block, dict) and "text" in block:
                    user_query = block["text"]
                    break

            if not user_query:
                return

            namespace = f"standup/actor/{self.dev_name}/facts"
            memories = self.client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=namespace,
                query=user_query,
                top_k=5,
            )

            if not memories:
                return

            # 검색된 기억을 텍스트로 조합
            context_parts = []
            for mem in memories:
                if isinstance(mem, dict):
                    content = mem.get("content", {})
                    if isinstance(content, dict):
                        text = content.get("text", "").strip()
                        if text:
                            context_parts.append(f"- {text}")

            if not context_parts:
                return

            context_text = "\n".join(context_parts)
            context_block = {
                "text": (
                    f"[이전 대화에서 알게 된 정보]\n{context_text}\n\n"
                    f"위 정보를 참고하되, 현재 질문에 관련된 내용만 활용하세요.\n\n"
                )
            }

            # 사용자 메시지 앞에 컨텍스트 삽입
            messages[-1]["content"].insert(0, context_block)
            logger.info("Retrieved %d memories for %s", len(context_parts), self.dev_name)

        except Exception as e:
            logger.warning("Failed to retrieve memories: %s", e)

    def save_interaction(self, event: AfterInvocationEvent):
        """호출 후: 사용자-어시스턴트 대화를 이벤트로 저장합니다."""
        try:
            messages = event.agent.messages
            if len(messages) < 2:
                return

            # 마지막 사용자 + 어시스턴트 메시지 쌍 추출
            interaction = []
            for msg in messages[-2:]:
                role = "USER" if msg["role"] == "user" else "ASSISTANT"
                text_parts = []
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "text" in block:
                        # 주입된 컨텍스트 블록 제외
                        if not block["text"].startswith("[이전 대화에서 알게 된 정보]"):
                            text_parts.append(block["text"])
                text = "\n".join(text_parts)
                if text:
                    interaction.append((text, role))

            if not interaction:
                return

            self.client.create_event(
                memory_id=self.memory_id,
                actor_id=self.dev_name,
                session_id=f"{self.dev_name}-standup",
                messages=interaction,
            )
            logger.info("Saved interaction for %s", self.dev_name)

        except Exception as e:
            logger.warning("Failed to save interaction: %s", e)

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.retrieve_context)
        registry.add_callback(AfterInvocationEvent, self.save_interaction)
```

- [ ] **Step 3: Commit**

```bash
git add shared/__init__.py shared/memory_hooks.py
git commit -m "feat: add StandupMemoryHooks for cross-session memory"
```

---

### Task 2: Integrate hooks into local agent

**Files:**
- Modify: `local-agent/strands_agent.py`
- Modify: `local-agent/chat.py`

- [ ] **Step 1: Modify `local-agent/strands_agent.py`**

Add `sys.path` setup, import hooks, and pass `hooks=` to `Agent()`. The full file becomes:

```python
"""
strands_agent.py — Strands 에이전트 (로컬 실행)

개발자별 SKILL.md를 로드하여 GitHub 활동 기반 스탠드업을 생성합니다.

사용법:
    uv run local-agent/strands_agent.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import shell, file_read

# 스크립트 기준 경로 설정 (CWD에 의존하지 않음)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# shared/ 패키지 임포트를 위한 경로 추가
sys.path.insert(0, str(PROJECT_ROOT))

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env")

# 개발자 이름으로 스킬 디렉토리 결정
dev_name = os.environ.get("DEV_NAME", "sejong")
skills_dir = str(PROJECT_ROOT / "skills" / dev_name)

# 메모리 훅 설정 (MEMORY_ID가 없으면 메모리 없이 동작)
hooks = []
memory_id = os.environ.get("MEMORY_ID")
if memory_id:
    from shared.memory_hooks import StandupMemoryHooks
    hooks = [StandupMemoryHooks(memory_id, dev_name)]

# 에이전트 생성
agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
    system_prompt=(
        f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
        f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
    ),
    tools=[shell, file_read],
    plugins=[AgentSkills(skills=skills_dir)],
    hooks=hooks,
)

if __name__ == "__main__":
    agent("오늘 업무 브리핑 해줘")
```

- [ ] **Step 2: Modify `local-agent/chat.py`**

Add `sys.path` setup after `PROJECT_ROOT`, import hooks conditionally, add `--date` flag, and update `create_agent()`. Changes to make:

After line 31 (`PROJECT_ROOT = SCRIPT_DIR.parent`), add:

```python
# shared/ 패키지 임포트를 위한 경로 추가
sys.path.insert(0, str(PROJECT_ROOT))
```

Replace the `create_agent` function (lines 43-61) with:

```python
def create_agent(dev_name: str, date_override: str | None = None) -> Agent:
    """개발자 이름에 맞는 Strands 에이전트를 생성합니다."""
    skills_dir = str(PROJECT_ROOT / "skills" / dev_name)
    if not Path(skills_dir).exists():
        print(f"{YELLOW}⚠ skills/{dev_name}/ 을 찾을 수 없습니다. 사용 가능한 개발자:{NC}")
        for d in (PROJECT_ROOT / "skills").iterdir():
            if d.is_dir():
                print(f"   - {d.name}")
        return None

    system_prompt = (
        f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
        f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
    )
    if date_override:
        from datetime import datetime
        weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        dt = datetime.strptime(date_override, "%Y-%m-%d")
        weekday = weekdays[dt.weekday()]
        system_prompt += f" 오늘은 {date_override} {weekday}입니다."

    hooks = []
    memory_id = os.environ.get("MEMORY_ID")
    if memory_id:
        from shared.memory_hooks import StandupMemoryHooks
        hooks = [StandupMemoryHooks(memory_id, dev_name)]

    return Agent(
        model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
        system_prompt=system_prompt,
        tools=[shell, file_read],
        plugins=[AgentSkills(skills=skills_dir)],
        callback_handler=null_callback_handler,
        hooks=hooks,
    )
```

Add `--date` argument to the argparser (after the `--dev_name` argument):

```python
    parser.add_argument("--date", default=None,
                        help="날짜 시뮬레이션 (YYYY-MM-DD, 데모용)")
```

Update the `create_agent` call to pass `date_override`:

```python
    agent = create_agent(dev_name, date_override=args.date)
```

Update the `/switch` handler to pass `date_override`:

```python
            new_agent = create_agent(new_name, date_override=args.date)
```

- [ ] **Step 3: Verify local agent starts without MEMORY_ID**

Run: `cd /home/ubuntu/developer-briefing-agent && uv run python -c "import sys; sys.path.insert(0, '.'); from shared.memory_hooks import StandupMemoryHooks; print('import OK')"`

Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
git add local-agent/strands_agent.py local-agent/chat.py
git commit -m "feat: integrate memory hooks + --date flag into local agent"
```

---

### Task 3: Integrate hooks into managed agentcore runtime

**Files:**
- Modify: `managed-agentcore/agentcore_runtime.py`
- Modify: `managed-agentcore/chat.py`

- [ ] **Step 1: Modify `managed-agentcore/agentcore_runtime.py`**

Add `import sys` and `sys.path` for local dev, import hooks, and update `create_agent()`. Changes:

After line 16 (`SCRIPT_DIR = Path(__file__).resolve().parent`), add:

```python
# 로컬 개발 시 shared/ 임포트 경로 (컨테이너에서는 COPY로 포함됨)
sys.path.insert(0, str(SCRIPT_DIR.parent))
```

Add `import sys` to the imports at top.

Replace the `create_agent` function (lines 36-48) with:

```python
def create_agent(dev_name: str) -> Agent:
    """개발자 이름에 맞는 Strands 에이전트를 생성합니다."""
    skills_dir = str(SCRIPT_DIR / "skills" / dev_name)

    hooks = []
    memory_id = os.environ.get("MEMORY_ID")
    if memory_id:
        from shared.memory_hooks import StandupMemoryHooks
        hooks = [StandupMemoryHooks(memory_id, dev_name)]

    return Agent(
        model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
        system_prompt=(
            f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
            f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
        ),
        tools=[shell, file_read],
        plugins=[AgentSkills(skills=skills_dir)],
        callback_handler=null_callback_handler,
        hooks=hooks,
    )
```

- [ ] **Step 2: Modify `managed-agentcore/chat.py`**

Add `--date` argument. After the `--dev_name` argument, add:

```python
    parser.add_argument("--date", default=None,
                        help="날짜 시뮬레이션 (YYYY-MM-DD, 데모용)")
```

Update `invoke_streaming` signature to accept `date_override`:

```python
def invoke_streaming(client, dev_name: str, prompt: str, date_override: str | None = None):
```

Replace the payload line inside `invoke_streaming`:

```python
    payload_dict = {"prompt": prompt, "dev_name": dev_name}
    if date_override:
        payload_dict["date"] = date_override
    payload = json.dumps(payload_dict)
```

Update the call site to pass `args.date`:

```python
        invoke_streaming(client, dev_name, user_input, date_override=args.date)
```

- [ ] **Step 3: Commit**

```bash
git add managed-agentcore/agentcore_runtime.py managed-agentcore/chat.py
git commit -m "feat: integrate memory hooks + --date flag into managed agentcore"
```

---

### Task 4: Create memory provisioning script

**Files:**
- Create: `setup/create_memory.py`

- [ ] **Step 1: Create `setup/create_memory.py`**

```python
#!/usr/bin/env python3
"""
create_memory.py — AgentCore Memory 리소스 생성

한 번만 실행하면 됩니다. MEMORY_ID를 local-agent/.env와 managed-agentcore/.env에 저장합니다.

사용법:
    uv run setup/create_memory.py
"""

from pathlib import Path

import boto3
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.constants import StrategyType

# 경로 설정
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# 터미널 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
NC = '\033[0m'

MEMORY_NAME = "developer-briefing-memory"


def update_env_file(env_path: Path, memory_id: str):
    """MEMORY_ID를 .env 파일에 추가하거나 업데이트합니다."""
    if not env_path.exists():
        return False

    lines = env_path.read_text().splitlines(keepends=True)

    # 기존 MEMORY_ID 제거
    lines = [line for line in lines if not line.startswith("MEMORY_ID=")]

    # 새 MEMORY_ID 추가
    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    lines.append(f"MEMORY_ID={memory_id}\n")

    env_path.write_text("".join(lines))
    return True


def main():
    print(f"\n{BLUE}{'='*50}{NC}")
    print(f"{BLUE}  AgentCore Memory 리소스 생성{NC}")
    print(f"{BLUE}{'='*50}{NC}\n")

    region = boto3.Session().region_name or "us-west-2"
    client = MemoryClient(region_name=region)

    # 기존 메모리 확인
    print(f"{YELLOW}기존 메모리 확인 중...{NC}")
    existing = client.list_memories()
    memory_id = None
    for mem in existing:
        if mem.get("name", "").startswith(MEMORY_NAME):
            memory_id = mem["id"]
            print(f"{GREEN}기존 메모리 발견: {memory_id}{NC}")
            break

    if not memory_id:
        # 새 메모리 생성
        print(f"{YELLOW}메모리 생성 중 (1~2분 소요)...{NC}")
        strategies = [
            {
                StrategyType.SEMANTIC.value: {
                    "name": "StandupFacts",
                    "description": "스탠드업 대화에서 추출된 사실과 컨텍스트",
                    "namespaces": ["standup/actor/{actorId}/facts"],
                }
            }
        ]

        memory = client.create_memory_and_wait(
            name=MEMORY_NAME,
            strategies=strategies,
            description="개발자 브리핑 에이전트 — 크로스 세션 메모리",
            event_expiry_days=90,
        )
        memory_id = memory["id"]
        print(f"{GREEN}메모리 생성 완료: {memory_id}{NC}")

    # .env 파일에 MEMORY_ID 저장
    print(f"\n{YELLOW}.env 파일 업데이트 중...{NC}")

    local_env = PROJECT_ROOT / "local-agent" / ".env"
    managed_env = PROJECT_ROOT / "managed-agentcore" / ".env"

    if update_env_file(local_env, memory_id):
        print(f"{GREEN}  local-agent/.env 업데이트 완료{NC}")
    else:
        print(f"{RED}  local-agent/.env 파일 없음 (먼저 setup.sh 실행){NC}")

    if update_env_file(managed_env, memory_id):
        print(f"{GREEN}  managed-agentcore/.env 업데이트 완료{NC}")
    else:
        print(f"{RED}  managed-agentcore/.env 파일 없음 (먼저 setup.sh 실행){NC}")

    print(f"\n{GREEN}완료! MEMORY_ID={memory_id}{NC}")
    print(f"이제 에이전트가 대화를 기억합니다.\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add setup/create_memory.py
git commit -m "feat: add memory provisioning script"
```

---

### Task 5: Update environment and container config

**Files:**
- Modify: `local-agent/.env.example`
- Modify: `managed-agentcore/.env.example`
- Modify: `managed-agentcore/01_create_agentcore_runtime.py`

- [ ] **Step 1: Add `MEMORY_ID` to `local-agent/.env.example`**

Append to the end of the file:

```
# AgentCore Memory ID (run: uv run setup/create_memory.py)
MEMORY_ID=
```

- [ ] **Step 2: Add `MEMORY_ID` to `managed-agentcore/.env.example`**

Append to the end of the file:

```
# AgentCore Memory ID (run: uv run setup/create_memory.py)
MEMORY_ID=
```

- [ ] **Step 3: Update deploy script to copy `shared/` into build context**

In `managed-agentcore/01_create_agentcore_runtime.py`, after the skills copy block (after line 71 `print(f"{GREEN}... 복사 완료...{NC}")`), add a similar block for `shared/`:

```python
    # shared/ 모듈도 빌드 컨텍스트로 복사
    src_shared = project_root / "shared"
    dst_shared = SCRIPT_DIR / "shared"

    if src_shared.exists():
        if dst_shared.exists():
            shutil.rmtree(dst_shared)
        shutil.copytree(src_shared, dst_shared)
        print(f"{GREEN}   shared/ 복사 완료{NC}")
    else:
        print(f"{YELLOW}   shared/ 없음 — 메모리 훅 없이 배포{NC}")
```

- [ ] **Step 4: Commit**

```bash
git add local-agent/.env.example managed-agentcore/.env.example managed-agentcore/01_create_agentcore_runtime.py
git commit -m "feat: add MEMORY_ID to env configs, copy shared/ in deploy script"
```

---

### Task 6: Update setup.sh with memory option

**Files:**
- Modify: `setup.sh`

- [ ] **Step 1: Update setup.sh**

Change step count from 3 to 4 in the headers:
- `=== 단계 1/3:` to `=== 단계 1/4:`
- `=== 단계 2/3:` to `=== 단계 2/4:`
- `=== 단계 3/3:` to `=== 단계 3/4:`

After the GitHub token `esac` block (around line 103), before the final completion section, add:

```bash
echo ""

# ── 단계 4: AgentCore 메모리 설정 (선택) ──────────
echo "=== 단계 4/4: AgentCore 메모리 설정 ==="
echo ""
echo "  AgentCore 메모리를 사용하면 에이전트가 이전 대화를 기억합니다."
echo ""
echo "  1) 메모리 생성 — AgentCore에 메모리 리소스 생성"
echo "  s) 건너뛰기 — 나중에 설정"
echo ""
echo -n "  선택 [1/s]: "
read -r mem_choice

case "$mem_choice" in
    1)
        echo ""
        uv run setup/create_memory.py
        ;;
    s|S|"")
        warn "건너뜀 — 나중에 uv run setup/create_memory.py 실행 가능"
        ;;
    *)
        warn "알 수 없는 선택 — 건너뜀"
        ;;
esac
```

- [ ] **Step 2: Commit**

```bash
git add setup.sh
git commit -m "feat: add memory setup step to setup.sh"
```

---

### Task 7: Manual verification

- [ ] **Step 1: Verify import works**

Run: `cd /home/ubuntu/developer-briefing-agent && uv run python -c "import sys; sys.path.insert(0, '.'); from shared.memory_hooks import StandupMemoryHooks; print('OK')"`

Expected: `OK`

- [ ] **Step 2: Verify --date flag is registered**

Run: `uv run local-agent/chat.py --help`

Expected: Help output includes `--date` argument.

- [ ] **Step 3: Verify setup script syntax**

Run: `uv run python -c "import ast; ast.parse(open('setup/create_memory.py').read()); print('syntax OK')"`

Expected: `syntax OK`
