#!/usr/bin/env python3
"""
01_create_agentcore_runtime.py — AgentCore Runtime 생성 및 배포

bedrock_agentcore_starter_toolkit을 사용하여 Docker 빌드, ECR 푸시, Runtime 배포를 수행합니다.

사용법:
    uv run managed-agentcore/01_create_agentcore_runtime.py

사전 조건:
    - AWS 자격 증명 설정 (aws configure)
    - bedrock-agentcore-starter-toolkit 설치 필요
    - SSM 토큰 조회를 위해 IAM 실행 역할에 ssm:GetParameter + kms:Decrypt 필요

수행 단계:
    1. 프로젝트 루트의 skills/를 빌드 컨텍스트로 복사
    2. Runtime 설정 (Dockerfile, ECR 저장소, IAM 역할 자동 생성)
    3. Runtime 배포 (Docker 빌드 → ECR 푸시 → AgentCore Runtime 생성)
    4. SSM Parameter Store 접근 권한 추가
    5. READY 상태 대기
    6. RUNTIME_ARN을 .env에 저장
"""

import json
import os
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import boto3

# managed-agentcore/ 디렉토리에서 실행 (Docker 빌드 컨텍스트)
SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)

# 터미널 색상
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
RED = '\033[0;31m'
NC = '\033[0m'

# 환경 변수 로드
load_dotenv(SCRIPT_DIR / ".env", override=True)
REGION = os.getenv("AWS_REGION")
AGENT_NAME = "developer_briefing_agent"


def main():
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}  개발자 브리핑 에이전트 — AgentCore Runtime 배포{NC}")
    print(f"{BLUE}{'='*60}{NC}\n")

    # ── 단계 0: 프로젝트 루트에서 스킬 복사 ─────────────────
    print(f"{YELLOW}[0/5] 스킬을 빌드 컨텍스트로 복사 중...{NC}")

    project_root = SCRIPT_DIR.parent
    src_skills = project_root / "skills"
    dst_skills = SCRIPT_DIR / "skills"

    if not src_skills.exists():
        print(f"{RED}❌ skills/ 를 찾을 수 없습니다: {src_skills}{NC}")
        sys.exit(1)

    if dst_skills.exists():
        shutil.rmtree(dst_skills)
    shutil.copytree(src_skills, dst_skills)

    print(f"{GREEN}✅ 복사 완료: {src_skills} → {dst_skills}{NC}")

    # shared/ 모듈도 빌드 컨텍스트로 복사
    src_shared = project_root / "shared"
    dst_shared = SCRIPT_DIR / "shared"

    if src_shared.exists():
        if dst_shared.exists():
            shutil.rmtree(dst_shared)
        shutil.copytree(src_shared, dst_shared)
        print(f"{GREEN}✅ 복사 완료: {src_shared} → {dst_shared}{NC}")
    else:
        print(f"{YELLOW}⚠ shared/ 없음 — 메모리 훅 없이 배포{NC}")

    print()

    # ── 단계 1: Runtime 설정 ──────────────────────────────────
    print(f"{YELLOW}[1/5] AgentCore Runtime 설정 중...{NC}")

    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit이 설치되지 않았습니다{NC}")
        print(f"   pip install bedrock-agentcore-starter-toolkit")
        sys.exit(1)

    agentcore_runtime = Runtime()

    response = agentcore_runtime.configure(
        agent_name=AGENT_NAME,
        entrypoint="agentcore_runtime.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=REGION,
        non_interactive=True,
    )

    print(f"{GREEN}✅ 설정 완료{NC}")
    print(f"   Dockerfile: {response.dockerfile_path}")
    print(f"   Config: {response.config_path}")
    print()

    # ── 단계 2: Runtime 배포 ─────────────────────────────────
    print(f"{YELLOW}[2/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...{NC}")
    print(f"   ⏳ 5~10분 소요\n")

    start_time = datetime.now()

    launch_result = agentcore_runtime.launch(
        env_vars={"STRANDS_NON_INTERACTIVE": "true"},
        auto_update_on_conflict=True,
    )

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{GREEN}✅ 배포 완료 ({elapsed:.0f}초){NC}")
    print(f"   Runtime ARN: {launch_result.agent_arn}")
    print(f"   Runtime ID:  {launch_result.agent_id}")
    print(f"   ECR URI:     {launch_result.ecr_uri}")
    print()

    # ── 단계 3: SSM 접근 권한 추가 ────────────────────────────
    print(f"{YELLOW}[3/5] 실행 역할에 SSM Parameter Store 권한 추가 중...{NC}")

    agentcore_control = boto3.client('bedrock-agentcore-control', region_name=REGION)
    runtime_info = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
    role_arn = runtime_info['roleArn']
    role_name = role_arn.split('/')[-1]
    account_id = role_arn.split(':')[4]

    iam = boto3.client('iam')
    ssm_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["ssm:GetParameter"],
                "Resource": f"arn:aws:ssm:{REGION}:{account_id}:parameter/developer-briefing-agent/*",
            },
            {
                "Effect": "Allow",
                "Action": ["kms:Decrypt"],
                "Resource": "*",
                "Condition": {
                    "StringEquals": {"kms:ViaService": f"ssm.{REGION}.amazonaws.com"}
                },
            },
        ],
    }

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="SSMParameterStoreAccess",
        PolicyDocument=json.dumps(ssm_policy),
    )
    print(f"{GREEN}✅ SSM 권한 추가 완료: {role_name}{NC}")
    print()

    # ── 단계 4: READY 상태 대기 ───────────────────────────────
    print(f"{YELLOW}[4/5] Runtime READY 상태 대기 중...{NC}")

    terminal_states = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']
    status = 'CREATING'
    max_attempts = 60  # 최대 10분

    for attempt in range(1, max_attempts + 1):
        time.sleep(10)
        try:
            resp = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
            status = resp['status']
            print(f"   [{attempt}/{max_attempts}] {status}")
        except Exception as e:
            print(f"   {RED}상태 확인 실패: {e}{NC}")
            break
        if status in terminal_states:
            break

    print()

    if status != 'READY':
        print(f"{RED}❌ Runtime 실패 (상태: {status}){NC}")
        print(f"   CloudWatch 로그 확인:")
        print(f"   aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow --region {REGION}")
        sys.exit(1)

    # ── 단계 5: .env에 저장 ───────────────────────────────────
    print(f"{YELLOW}[5/5] Runtime 정보를 .env에 저장 중...{NC}")

    env_file = SCRIPT_DIR / ".env"

    # 기존 .env에서 이전 런타임 정보 제거
    if env_file.exists():
        with open(env_file, 'r') as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith("RUNTIME_ARN=")
                and not line.startswith("RUNTIME_ID=")
                and not line.startswith("RUNTIME_NAME=")
                and not line.strip().startswith("# AgentCore Runtime")
            ]
    else:
        lines = []

    # 런타임 정보 추가
    lines.append(f"\n# AgentCore Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"RUNTIME_ID={launch_result.agent_id}\n")

    with open(env_file, 'w') as f:
        f.writelines(lines)

    print(f"{GREEN}✅ Runtime 준비 완료!{NC}")
    print(f"   RUNTIME_ARN이 .env에 저장되었습니다\n")

    # ── 완료 요약 ─────────────────────────────────────────────
    print(f"{BLUE}{'='*60}{NC}")
    print(f"{GREEN}  배포 완료!{NC}")
    print(f"{BLUE}{'='*60}{NC}")
    print(f"   Runtime 이름: {AGENT_NAME}")
    print(f"   Runtime ARN:  {launch_result.agent_arn}")
    print(f"   리전:          {REGION}")
    print()
    print(f"   다음 단계:")
    print(f"   1. 호출 테스트: uv run managed-agentcore/02_invoke_agentcore_runtime.py")
    print(f"   2. 다른 개발자로 호출:")
    print(f"      uv run managed-agentcore/02_invoke_agentcore_runtime.py --dev_name sunshin")
    print(f"   3. 대화형 채팅: uv run managed-agentcore/chat.py")
    print(f"   4. 로그 확인:")
    print(f"      aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow --region {REGION}")
    print()


if __name__ == "__main__":
    main()
