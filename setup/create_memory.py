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
