"""
strands_agent.py — Strands 에이전트 (로컬 실행)

개발자별 SKILL.md를 시스템 프롬프트에 직접 inline (static loading) 하여
GitHub 활동 기반 스탠드업을 생성합니다. AgentSkills 플러그인을 사용하지
않으므로 cachePoint가 보존되어 Turn 1 prompt caching이 정상 작동합니다.

사용법:
    uv run local-agent/strands_agent.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from strands import Agent
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
skills_dir = PROJECT_ROOT / "skills" / dev_name

# 메모리 훅 설정 (MEMORY_ID가 없으면 메모리 없이 동작)
hooks = []
memory_id = os.environ.get("MEMORY_ID")
if memory_id:
    from shared.memory_hooks import StandupMemoryHooks
    hooks = [StandupMemoryHooks(memory_id, dev_name)]

# 시스템 프롬프트 + Active Skill을 직접 결합 (static loading)
base_prompt = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text()
base_prompt = base_prompt.replace("{dev_name}", dev_name)

skill_content = (skills_dir / "SKILL.md").read_text()
skill_content = skill_content.replace("{skill_dir}", str(skills_dir))

combined_prompt = f"{base_prompt}\n\n## Active Skill\n\n{skill_content}"

agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6", cache_tools="default"),
    system_prompt=[
        SystemContentBlock(text=combined_prompt),
        SystemContentBlock(cachePoint={"type": "default"}),
    ],
    tools=[shell, file_read],
    hooks=hooks,
)

if __name__ == "__main__":
    agent("오늘 업무 브리핑 해줘")
