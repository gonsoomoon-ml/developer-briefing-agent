#!/usr/bin/env python3
"""
chat.py — 대화형 터미널 채팅 (AgentCore Runtime 원격 호출)

배포된 AgentCore Runtime에 요청을 보내고 SSE 스트리밍으로 응답을 받습니다.

사용법:
    uv run managed-agentcore/chat.py
    uv run managed-agentcore/chat.py --dev_name sunshin

명령어:
    /switch <이름>  — 개발자 전환 (예: /switch sunshin)
    /quit 또는 quit — 종료

사전 조건:
    - 01_create_agentcore_runtime.py 실행 필요 (.env에 RUNTIME_ARN 생성됨)
"""

import json
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# 경로 설정
SCRIPT_DIR = Path(__file__).resolve().parent

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env", override=True)

REGION = os.getenv("AWS_REGION")
RUNTIME_ARN = os.getenv("RUNTIME_ARN")

# 터미널 색상
GREEN = '\033[0;32m'
CYAN = '\033[0;36m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
DIM = '\033[2m'
NC = '\033[0m'


def parse_sse_event(sse_bytes):
    """SSE(Server-Sent Events) 데이터 라인을 파싱합니다."""
    if not sse_bytes:
        return None
    try:
        text = sse_bytes.decode("utf-8").strip()
        if text.startswith("data: "):
            text = text[6:]
        return json.loads(text) if text else None
    except Exception:
        return None


def invoke_streaming(client, dev_name: str, prompt: str, date_override: str | None = None):
    """런타임을 호출하고 스트리밍 응답을 출력합니다."""
    payload_dict = {"prompt": prompt, "dev_name": dev_name}
    if date_override:
        payload_dict["date"] = date_override
    payload = json.dumps(payload_dict)

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier="DEFAULT",
            payload=payload,
        )

        content_type = response.get("contentType", "")

        if "text/event-stream" in content_type:
            # SSE 스트리밍 응답 처리
            for line in response["response"].iter_lines(chunk_size=1):
                event = parse_sse_event(line)
                if event is None:
                    continue
                if isinstance(event, str):
                    print(event, end="", flush=True)
                elif isinstance(event, dict):
                    text = event.get("text", event.get("content", ""))
                    if text:
                        print(text, end="", flush=True)
        else:
            # 비스트리밍 응답 처리
            body = response["response"].read().decode("utf-8")
            try:
                result = json.loads(body)
                print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(body)

    except Exception as e:
        print(f"\n{RED}❌ 오류: {e}{NC}")

    print()


def main():
    parser = argparse.ArgumentParser(description="개발자 브리핑 에이전트 대화형 채팅 (AgentCore Runtime)")
    parser.add_argument("--dev_name", default=os.getenv("DEV_NAME", "sejong"),
                        help="개발자 이름 (기본값: .env의 DEV_NAME)")
    parser.add_argument("--date", default=None,
                        help="날짜 시뮬레이션 (YYYY-MM-DD, 데모용)")
    args = parser.parse_args()

    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN이 .env에 설정되지 않았습니다{NC}")
        print(f"   먼저 01_create_agentcore_runtime.py를 실행하세요")
        sys.exit(1)

    dev_name = args.dev_name

    # boto3 클라이언트 생성
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        config=Config(
            connect_timeout=300,
            read_timeout=600,
            retries={"max_attempts": 0},
        ),
    )

    print(f"\n{CYAN}{'='*50}{NC}")
    print(f"{CYAN}  개발자 브리핑 에이전트 ({dev_name}){NC}")
    print(f"{CYAN}  AgentCore Runtime 원격 호출{NC}")
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
            dev_name = user_input.split(" ", 1)[1].strip()
            print(f"{YELLOW}{dev_name}(으)로 전환했습니다{NC}\n")
            continue

        print()
        invoke_streaming(client, dev_name, user_input, date_override=args.date)
        print()


if __name__ == "__main__":
    main()
