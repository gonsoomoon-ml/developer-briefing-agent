"""
agentcore_runtime.py — AgentCore Runtime 엔트리포인트

Strands 에이전트를 BedrockAgentCoreApp으로 래핑하여 팀 서비스로 배포합니다.
공식 Strands 튜토리얼 패턴에 따라 Agent를 모듈 레벨에서 캐싱하여
요청 간 agent.messages를 유지합니다 (멀티턴 대화 연속성).
멀티 개발자 지원을 위해 session_id 키로 Agent를 분리합니다.
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
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
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

# 모듈 레벨 Agent 캐시 — 컨테이너 수명 동안 유지 (공식 Strands 튜토리얼 패턴)
# key = "dev_name:session_id", value = Agent 인스턴스
_session_agents: dict[str, Agent] = {}


def create_agent(dev_name: str, session_id: str | None = None) -> Agent:
    """개발자 이름에 맞는 Strands 에이전트를 생성합니다.

    SKILL.md를 직접 시스템 프롬프트에 inline (static loading) 합니다.
    AgentSkills 플러그인을 쓰지 않으므로 cachePoint가 보존되어 Turn 1
    prompt caching이 정상 작동합니다.
    """
    skills_dir = SCRIPT_DIR / "skills" / dev_name
    if not skills_dir.exists():
        skills_dir = SCRIPT_DIR.parent / "skills" / dev_name

    hooks = []
    memory_id = os.environ.get("MEMORY_ID")
    if memory_id:
        from shared.memory_hooks import StandupMemoryHooks
        hooks = [StandupMemoryHooks(memory_id, dev_name, session_id=session_id)]

    from strands.types.content import SystemContentBlock

    prompt_path = SCRIPT_DIR / "prompts" / "system_prompt.md"
    if not prompt_path.exists():
        prompt_path = SCRIPT_DIR.parent / "prompts" / "system_prompt.md"
    base_prompt = prompt_path.read_text().replace("{dev_name}", dev_name)

    skill_content = (skills_dir / "SKILL.md").read_text()
    skill_content = skill_content.replace("{skill_dir}", str(skills_dir))

    combined_prompt = f"{base_prompt}\n\n## Active Skill\n\n{skill_content}"

    return Agent(
        model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6", cache_tools="default"),
        system_prompt=[
            SystemContentBlock(text=combined_prompt),
            SystemContentBlock(cachePoint={"type": "default"}),
        ],
        tools=[shell, file_read],
        conversation_manager=SlidingWindowConversationManager(window_size=20),
        callback_handler=null_callback_handler,
        hooks=hooks,
    )


def _get_or_create_agent(dev_name: str, session_id: str | None = None) -> Agent:
    """세션별 Agent를 캐시에서 가져오거나 새로 생성합니다."""
    cache_key = f"{dev_name}:{session_id or 'default'}"

    if cache_key in _session_agents:
        agent = _session_agents[cache_key]
        print(f"[runtime] REUSE agent for {cache_key} ({len(agent.messages)} prior messages)")
        return agent

    agent = create_agent(dev_name, session_id=session_id)
    _session_agents[cache_key] = agent
    print(f"[runtime] NEW agent for {cache_key}")
    return agent


@app.entrypoint
async def standup_agent(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    """에이전트 응답을 SSE 스트리밍으로 전달합니다."""
    dev_name = payload.get("dev_name", os.environ.get("DEV_NAME", "sejong"))
    session_id = payload.get("session_id")
    agent = _get_or_create_agent(dev_name, session_id=session_id)
    prompt = payload.get("prompt", "오늘 업무 브리핑 해줘")

    async for event in agent.stream_async(prompt):
        data = event.get("data", "")
        if data:
            yield {"type": "agent_text_stream", "text": data}

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
