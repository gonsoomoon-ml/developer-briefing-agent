#!/usr/bin/env python3
"""
02_invoke_agentcore_runtime.py — AgentCore Runtime 단일 호출 테스트

배포된 AgentCore Runtime에 요청을 보내고 스트리밍 응답을 출력합니다.

사용법:
    # 기본값 (.env의 DEV_NAME 사용)
    uv run managed-agentcore/02_invoke_agentcore_runtime.py

    # 개발자 이름 지정
    uv run managed-agentcore/02_invoke_agentcore_runtime.py --dev_name sunshin

    # 커스텀 프롬프트
    uv run managed-agentcore/02_invoke_agentcore_runtime.py --prompt "리뷰할 PR 있어?"

사전 조건:
    - 01_create_agentcore_runtime.py 실행 필요 (.env에 RUNTIME_ARN 생성됨)
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# 경로 설정
SCRIPT_DIR = Path(__file__).resolve().parent

# 터미널 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
NC = '\033[0m'

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env", override=True)

REGION = boto3.Session().region_name or os.getenv("AWS_REGION", "us-east-1")
RUNTIME_ARN = os.getenv("RUNTIME_ARN")


def parse_args():
    parser = argparse.ArgumentParser(description="개발자 브리핑 에이전트 — AgentCore Runtime 호출")
    parser.add_argument(
        "--dev_name",
        type=str,
        default=os.getenv("DEV_NAME", "sejong"),
        help="개발자 이름 — 로드할 SKILL.md 결정 (기본값: .env의 DEV_NAME)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="오늘 업무 브리핑 해줘",
        help="에이전트에 보낼 프롬프트",
    )
    return parser.parse_args()


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


def main():
    args = parse_args()

    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN이 .env에 설정되지 않았습니다{NC}")
        print(f"   먼저 01_create_agentcore_runtime.py를 실행하세요")
        sys.exit(1)

    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}  개발자 브리핑 에이전트 — AgentCore Runtime 호출{NC}")
    print(f"{BLUE}{'='*60}{NC}")
    print(f"   Runtime:   {RUNTIME_ARN}")
    print(f"   개발자:     {args.dev_name}")
    print(f"   프롬프트:   {args.prompt}")
    print(f"   리전:       {REGION}")
    print(f"{BLUE}{'='*60}{NC}\n")

    # boto3 클라이언트 생성 (타임아웃 확장)
    client_config = Config(
        connect_timeout=300,
        read_timeout=600,
        retries={"max_attempts": 0},
    )
    agentcore_client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        config=client_config,
    )

    # 요청 페이로드 구성
    payload = {
        "prompt": args.prompt,
        "dev_name": args.dev_name,
    }

    print(f"📤 요청 전송 중...\n")
    start_time = datetime.now()

    try:
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier="DEFAULT",
            payload=json.dumps(payload),
        )

        # 응답 처리
        content_type = response.get("contentType", "")

        if "text/event-stream" in content_type:
            # SSE 스트리밍 응답
            print(f"📥 스트리밍 응답:\n")
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
            # 비스트리밍 응답
            body = response["response"].read().decode("utf-8")
            try:
                result = json.loads(body)
                print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(body)

    except Exception as e:
        print(f"\n{RED}❌ 호출 실패: {e}{NC}")
        sys.exit(1)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n\n{GREEN}{'='*60}{NC}")
    print(f"{GREEN}✅ 완료 ({elapsed:.1f}초){NC}")
    print(f"{GREEN}{'='*60}{NC}\n")


if __name__ == "__main__":
    main()
