#!/usr/bin/env bash
set -euo pipefail

# ── 터미널 색상 ────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}[완료]${NC} $1"; }
fail() { echo -e "${RED}[실패]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[정보]${NC} $1"; }
warn() { echo -e "${YELLOW}[건너뜀]${NC} $1"; }

# 프로젝트 루트에서 실행
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  개발자 브리핑 에이전트 — 초기 설정${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ── 단계 1: 의존성 설치 ───────────────────────────
echo "=== 단계 1/3: Python 의존성 설치 ==="

if ! command -v uv &>/dev/null; then
    fail "'uv'를 찾을 수 없습니다. 설치: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

uv sync
pass "의존성 설치 완료 (uv sync)"
echo ""

# ── 단계 2: .env 파일 생성 ────────────────────────
echo "=== 단계 2/3: .env 파일 설정 ==="

# local-agent/.env
if [[ -f local-agent/.env ]]; then
    warn "local-agent/.env 이미 존재 (덮어쓰지 않음)"
else
    cp local-agent/.env.example local-agent/.env
    pass "local-agent/.env 생성 완료"
    info "local-agent/.env에서 GITHUB_TOKEN과 DEV_NAME을 설정하세요"
fi

# managed-agentcore/.env
if [[ -f managed-agentcore/.env ]]; then
    warn "managed-agentcore/.env 이미 존재 (덮어쓰지 않음)"
else
    cp managed-agentcore/.env.example managed-agentcore/.env
    pass "managed-agentcore/.env 생성 완료"
fi

echo ""

# ── 단계 3: GitHub 토큰 설정 (선택) ──────────────
echo "=== 단계 3/3: GitHub 토큰 설정 ==="
echo ""
echo "  GitHub 토큰 제공 방법을 선택하세요:"
echo ""
echo "  1) 수동 입력 — local-agent/.env에 토큰 저장"
echo "  2) AWS SSM  — Parameter Store에 안전하게 저장 (권장)"
echo "  s) 건너뛰기 — 나중에 설정"
echo ""
echo -n "  선택 [1/2/s]: "
read -r choice

case "$choice" in
    1)
        echo ""
        echo -n "  GitHub Personal Access Token 입력 (ghp_...): "
        read -rs token
        echo ""
        if [[ -z "$token" ]]; then
            warn "토큰이 입력되지 않았습니다"
        else
            # local-agent/.env에 토큰 저장
            if grep -q "^GITHUB_TOKEN=" local-agent/.env 2>/dev/null; then
                sed -i "s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$token|" local-agent/.env
            else
                echo "GITHUB_TOKEN=$token" >> local-agent/.env
            fi
            pass "토큰이 local-agent/.env에 저장되었습니다"
        fi
        ;;
    2)
        echo ""
        if [[ -f setup/store_github_token.sh ]]; then
            bash setup/store_github_token.sh
        else
            fail "setup/store_github_token.sh를 찾을 수 없습니다"
        fi
        ;;
    s|S|"")
        warn "건너뜀 — 에이전트 실행 전에 local-agent/.env에 GITHUB_TOKEN을 설정하세요"
        ;;
    *)
        warn "알 수 없는 선택 — 건너뜀"
        ;;
esac

echo ""

# ── 설정 완료 ─────────────────────────────────────
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  설정 완료!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
info "설치 확인:"
echo "  uv run python -c \"from strands import Agent; print('OK')\""
echo ""
info "로컬 에이전트 실행:"
echo "  uv run local-agent/chat.py"
echo ""
info "AgentCore Runtime 배포:"
echo "  uv run managed-agentcore/01_create_agentcore_runtime.py"
echo "  uv run managed-agentcore/chat.py"
echo ""
