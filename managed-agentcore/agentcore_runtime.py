"""
agentcore_runtime.py — AgentCore Runtime 엔트리포인트

Strands 에이전트를 BedrockAgentCoreApp으로 래핑하여 팀 서비스로 배포합니다.
요청별로 dev_name을 받아 해당 개발자의 SKILL.md를 로드합니다.
SSE 스트리밍으로 실시간 응답을 전달합니다.

사용법:
    # 프로덕션 (AgentCore 배포)
    01_create_agentcore_runtime.py로 배포

    # 로컬 테스트
    uv run managed-agentcore/agentcore_runtime.py
"""

import os
from pathlib import Path
from typing import Any, AsyncGenerator
from dotenv import load_dotenv
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import shell, file_read
from strands.handlers.callback_handler import null_callback_handler
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# 경로 설정
SCRIPT_DIR = Path(__file__).resolve().parent

# 환경 변수 로드 (컨테이너에서는 .env 없이 IAM 역할 사용)
load_dotenv(SCRIPT_DIR / ".env")

# AgentCore 앱 초기화
app = BedrockAgentCoreApp()


def create_agent(dev_name: str) -> Agent:
    """개발자 이름에 맞는 Strands 에이전트를 생성합니다."""
    skills_dir = str(SCRIPT_DIR / "skills" / dev_name)
    return Agent(
        model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
        system_prompt=(
            f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
            f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
        ),
        tools=[shell, file_read],
        plugins=[AgentSkills(skills=skills_dir)],
        callback_handler=null_callback_handler,
    )


@app.entrypoint
async def standup_agent(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    """에이전트 응답을 SSE 스트리밍으로 전달합니다."""
    dev_name = payload.get("dev_name", os.environ.get("DEV_NAME", "sejong"))
    agent = create_agent(dev_name)
    prompt = payload.get("prompt", "오늘 업무 브리핑 해줘")

    async for event in agent.stream_async(prompt):
        # 텍스트 청크를 생성되는 대로 스트리밍
        data = event.get("data", "")
        if data:
            yield {"type": "agent_text_stream", "text": data}

    yield {"type": "workflow_complete", "text": ""}


if __name__ == "__main__":
    app.run()
