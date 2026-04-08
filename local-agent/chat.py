#!/usr/bin/env python3
"""
chat.py — 대화형 터미널 채팅 (로컬 에이전트)

개발자별 스탠드업 어시스턴트와 대화합니다.
스트리밍 출력, 대화 컨텍스트 유지, /switch로 개발자 전환을 지원합니다.

사용법:
    uv run local-agent/chat.py
    uv run local-agent/chat.py --dev_name sunshin

명령어:
    /switch <이름>  — 개발자 전환 (예: /switch sunshin)
    /quit 또는 quit — 종료
"""

import os
import sys
import asyncio
import argparse
from pathlib import Path
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands.handlers.callback_handler import null_callback_handler
from strands_tools import shell, file_read
from dotenv import load_dotenv

# 경로 설정
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# shared/ 패키지 임포트를 위한 경로 추가
sys.path.insert(0, str(PROJECT_ROOT))

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env")

# 터미널 색상
GREEN = '\033[0;32m'
CYAN = '\033[0;36m'
YELLOW = '\033[1;33m'
DIM = '\033[2m'
NC = '\033[0m'


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


async def stream_response(agent: Agent, prompt: str):
    """에이전트 응답을 스트리밍으로 출력합니다."""
    async for event in agent.stream_async(prompt):
        data = event.get("data", "")
        if data:
            print(data, end="", flush=True)
    print()


def main():
    parser = argparse.ArgumentParser(description="개발자 브리핑 에이전트 대화형 채팅")
    parser.add_argument("--dev_name", default=os.getenv("DEV_NAME", "sejong"),
                        help="개발자 이름 (기본값: .env의 DEV_NAME)")
    parser.add_argument("--date", default=None,
                        help="날짜 시뮬레이션 (YYYY-MM-DD, 데모용)")
    args = parser.parse_args()

    dev_name = args.dev_name
    agent = create_agent(dev_name, date_override=args.date)
    if not agent:
        sys.exit(1)

    print(f"\n{CYAN}{'='*50}{NC}")
    print(f"{CYAN}  개발자 브리핑 에이전트 ({dev_name}){NC}")
    print(f"{CYAN}{'='*50}{NC}")
    print(f"{DIM}  /switch <이름> — 개발자 전환{NC}")
    print(f"{DIM}  /quit          — 종료{NC}")
    print()

    while True:
        try:
            user_input = input(f"{GREEN}> {NC}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "quit", "exit"):
            break

        if user_input.startswith("/switch "):
            new_name = user_input.split(" ", 1)[1].strip()
            new_agent = create_agent(new_name, date_override=args.date)
            if new_agent:
                dev_name = new_name
                agent = new_agent
                print(f"{YELLOW}{dev_name}(으)로 전환했습니다{NC}\n")
            continue

        print()
        asyncio.run(stream_response(agent, user_input))
        print()


if __name__ == "__main__":
    main()
