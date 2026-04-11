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
from strands.types.content import SystemContentBlock
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
# 시스템 프롬프트 로드
prompt_path = PROJECT_ROOT / "prompts" / "system_prompt.md"
system_prompt_text = prompt_path.read_text().replace("{dev_name}", dev_name)

# TODO(strands-agents/sdk-python AgentSkills cachePoint bug): Turn 1 caching
# is currently a no-op. AgentSkills._on_before_invocation reads/writes
# agent.system_prompt via the string getter/setter, and the setter routes
# through Agent._initialize_system_prompt which rebuilds _system_prompt_content
# as [{"text": str}] — dropping any non-text SystemContentBlocks (including
# cachePoint). cache_tools="default" is stripped the same way. These lines
# are intentionally retained: once Strands fixes AgentSkills to preserve the
# content-block list, Turn 1 caching will reactivate with no code change here.
# Turn 2+ caching still works via shared/memory_hooks.py (message-list path,
# untouched by AgentSkills). See docs/prompt-caching.md for measurements.
agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6", cache_tools="default"),
    system_prompt=[
        SystemContentBlock(text=system_prompt_text),
        SystemContentBlock(cachePoint={"type": "default"}),
    ],
    tools=[shell, file_read],
    plugins=[AgentSkills(skills=skills_dir)],
    hooks=hooks,
)

if __name__ == "__main__":
    agent("오늘 업무 브리핑 해줘")
