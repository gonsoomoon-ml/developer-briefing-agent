import os
from dotenv import load_dotenv
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import shell, file_read

load_dotenv()

dev_name = os.environ.get("DEV_NAME", "sejong")

agent = Agent(
    model=BedrockModel(model_id="global.anthropic.claude-sonnet-4-6"),
    system_prompt=(
        f"당신은 {dev_name}의 일일 스탠드업 어시스턴트입니다. "
        f"모든 응답과 중간 메시지를 자연스러운 한국어 존댓말로 작성하세요."
    ),
    tools=[shell, file_read],
    plugins=[AgentSkills(skills=f"./skills/{dev_name}/")],
)

if __name__ == "__main__":
    agent("Write my standup for today")
