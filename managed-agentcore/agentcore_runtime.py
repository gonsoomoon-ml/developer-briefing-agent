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
import sys
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

# 로컬 개발 시 shared/ 임포트 경로 (컨테이너에서는 COPY로 포함됨)
sys.path.insert(0, str(SCRIPT_DIR.parent))

# 환경 변수 로드 (컨테이너에서는 .env 없이 IAM 역할 사용)
load_dotenv(SCRIPT_DIR / ".env")

# AgentCore 앱 초기화
app = BedrockAgentCoreApp()


def create_agent(dev_name: str) -> Agent:
    """개발자 이름에 맞는 Strands 에이전트를 생성합니다."""
    skills_dir = str(SCRIPT_DIR / "skills" / dev_name)

    hooks = []
    memory_id = os.environ.get("MEMORY_ID")
    if memory_id:
        from shared.memory_hooks import StandupMemoryHooks
        hooks = [StandupMemoryHooks(memory_id, dev_name)]

    from strands.types.content import SystemContentBlock

    prompt_path = SCRIPT_DIR / "prompts" / "system_prompt.md"
    if not prompt_path.exists():
        # 프로젝트 루트에서 찾기 (로컬 개발 시)
        prompt_path = SCRIPT_DIR.parent / "prompts" / "system_prompt.md"
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
    return Agent(
        model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6", cache_tools="default"),
        system_prompt=[
            SystemContentBlock(text=system_prompt_text),
            SystemContentBlock(cachePoint={"type": "default"}),
        ],
        tools=[shell, file_read],
        plugins=[AgentSkills(skills=skills_dir)],
        callback_handler=null_callback_handler,
        hooks=hooks,
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

    # 토큰 사용량 전송
    if hasattr(agent, "event_loop_metrics") and hasattr(agent.event_loop_metrics, "accumulated_usage"):
        usage = agent.event_loop_metrics.accumulated_usage
        yield {"type": "token_usage", "usage": {
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "total_tokens": usage.get("totalTokens", 0),
            "cache_read_input_tokens": usage.get("cacheReadInputTokens", 0),
            "cache_write_input_tokens": usage.get("cacheWriteInputTokens", 0),
        }}

    yield {"type": "workflow_complete", "text": ""}


if __name__ == "__main__":
    app.run()
