"""
strands_agent.py — Strands 에이전트 (로컬 실행)

개발자별 SKILL.md를 로드하여 GitHub 활동 기반 스탠드업을 생성합니다.

사용법:
    uv run local-agent/strands_agent.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import shell, file_read

# 스크립트 기준 경로 설정 (CWD에 의존하지 않음)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env")

# 개발자 이름으로 스킬 디렉토리 결정
dev_name = os.environ.get("DEV_NAME", "sejong")
skills_dir = str(PROJECT_ROOT / "skills" / dev_name)

# 에이전트 생성
agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
    system_prompt=(
        f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
        f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
    ),
    tools=[shell, file_read],
    plugins=[AgentSkills(skills=skills_dir)],
)

if __name__ == "__main__":
    agent("오늘 업무 브리핑 해줘")
