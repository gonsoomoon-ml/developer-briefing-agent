#!/usr/bin/env bash
set -euo pipefail

PARAM_NAME="/developer-briefing-agent/github-token"

# ── 터미널 색상 ────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[통과]${NC} $1"; }
fail() { echo -e "${RED}[실패]${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}[주의]${NC} $1"; }
info() { echo -e "       $1"; }

# ── 단계 1: AWS 자격 증명 확인 ────────────────────
echo ""
echo "=== 단계 1/5: AWS 자격 증명 확인 ==="
if ! identity=$(aws sts get-caller-identity --output json 2>&1); then
    fail "AWS 자격 증명이 설정되지 않았습니다. 먼저 'aws configure'를 실행하세요."
fi

account=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
arn=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
pass "인증 완료: $arn (계정: $account)"

# ── 단계 2: IAM 권한 확인 ─────────────────────────
echo ""
echo "=== 단계 2/5: IAM 권한 확인 ==="

missing_perms=()

# ssm:PutParameter 확인
if aws ssm put-parameter \
    --name "$PARAM_NAME" \
    --type SecureString \
    --value "permission-check-dummy" \
    --dry-run \
    >/dev/null 2>&1; then
    pass "ssm:PutParameter"
else
    # SSM은 dry-run을 지원하지 않으므로 저장 단계에서 확인
    warn "ssm:PutParameter — 사전 검증 불가 (저장 단계에서 확인)"
fi

# ssm:GetParameter 확인
if aws ssm get-parameter --name "$PARAM_NAME" --with-decryption >/dev/null 2>&1; then
    pass "ssm:GetParameter + kms:Decrypt (파라미터 이미 존재)"
else
    error_msg=$(aws ssm get-parameter --name "$PARAM_NAME" --with-decryption 2>&1 || true)
    if echo "$error_msg" | grep -q "ParameterNotFound"; then
        pass "ssm:GetParameter + kms:Decrypt (파라미터 미생성, 권한 확인됨)"
    elif echo "$error_msg" | grep -q "AccessDeniedException"; then
        missing_perms+=("ssm:GetParameter or kms:Decrypt")
        fail "권한 부족: ssm:GetParameter 또는 kms:Decrypt
       IAM 역할/사용자에 다음 권한이 필요합니다:
         - ssm:GetParameter
         - ssm:PutParameter
         - kms:Decrypt (SecureString 복호화)"
    else
        warn "ssm:GetParameter — 예상치 못한 응답, 계속 진행"
        info "$error_msg"
    fi
fi

# ── 단계 3: GitHub 토큰 입력 ──────────────────────
echo ""
echo "=== 단계 3/5: GitHub 토큰 입력 ==="

if [[ "${1:-}" == "--token" && -n "${2:-}" ]]; then
    token="$2"
    info "--token 인자에서 토큰을 가져왔습니다"
else
    echo -n "GitHub Personal Access Token 입력 (ghp_...): "
    read -rs token
    echo ""
fi

if [[ -z "$token" ]]; then
    fail "토큰이 비어있습니다."
fi

if [[ ! "$token" =~ ^gh[ps]_ ]]; then
    warn "토큰이 'ghp_' 또는 'ghs_'로 시작하지 않습니다 — GitHub PAT가 맞나요?"
fi

pass "토큰 수신 완료 (${#token}자)"

# ── 단계 4: SSM에 저장 ────────────────────────────
echo ""
echo "=== 단계 4/5: SSM Parameter Store에 토큰 저장 ==="

if aws ssm put-parameter \
    --name "$PARAM_NAME" \
    --type SecureString \
    --value "$token" \
    --overwrite \
    --output json >/dev/null 2>&1; then
    pass "SecureString으로 저장 완료: $PARAM_NAME"
else
    fail "파라미터 저장 실패. IAM 권한을 확인하세요:
       - ssm:PutParameter
       - kms:Encrypt (SecureString 암호화)"
fi

# ── 단계 5: 검증 ──────────────────────────────────
echo ""
echo "=== 단계 5/5: 검증 ==="

# 5a: SSM에서 읽기 검증
readback=$(aws ssm get-parameter \
    --name "$PARAM_NAME" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text 2>&1) || fail "SSM에서 파라미터를 읽을 수 없습니다."

if [[ "$readback" == "$token" ]]; then
    pass "SSM 읽기 검증 통과"
else
    fail "SSM에서 읽은 값이 저장한 토큰과 일치하지 않습니다!"
fi

# 5b: GitHub API 테스트
echo ""
github_user=$(curl -sf -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/user 2>&1) || fail "GitHub API 호출 실패. 토큰이 유효한지 확인하세요."

username=$(echo "$github_user" | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))" 2>/dev/null)

if [[ -n "$username" ]]; then
    pass "GitHub API 인증 확인 — 사용자: $username"
else
    fail "GitHub API에서 예상치 못한 응답을 받았습니다."
fi

# ── 완료 ──────────────────────────────────────────
echo ""
echo -e "${GREEN}=== 모든 검증 통과! ===${NC}"
echo ""
info "토큰이 SSM Parameter Store에 안전하게 저장되었습니다."
info ""
