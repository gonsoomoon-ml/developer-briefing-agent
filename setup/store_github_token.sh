#!/usr/bin/env bash
set -euo pipefail

PARAM_NAME="/developer-briefing-agent/github-token"

# ── Colors ──────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "       $1"; }

# ── Step 1: Check AWS identity ─────────────────
echo ""
echo "=== Step 1/5: Checking AWS credentials ==="
if ! identity=$(aws sts get-caller-identity --output json 2>&1); then
    fail "AWS credentials not configured. Run 'aws configure' first."
fi

account=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
arn=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
pass "Authenticated as: $arn (account: $account)"

# ── Step 2: Check IAM permissions ──────────────
echo ""
echo "=== Step 2/5: Checking IAM permissions ==="

missing_perms=()

# Check ssm:PutParameter
if aws ssm put-parameter \
    --name "$PARAM_NAME" \
    --type SecureString \
    --value "permission-check-dummy" \
    --dry-run \
    >/dev/null 2>&1; then
    pass "ssm:PutParameter"
else
    # dry-run not supported for SSM, so try a describe instead
    # If we can get-parameter or it doesn't exist yet, we likely have put access
    warn "ssm:PutParameter — cannot verify in advance (will test during store step)"
fi

# Check ssm:GetParameter
if aws ssm get-parameter --name "$PARAM_NAME" --with-decryption >/dev/null 2>&1; then
    pass "ssm:GetParameter + kms:Decrypt (parameter already exists)"
else
    error_msg=$(aws ssm get-parameter --name "$PARAM_NAME" --with-decryption 2>&1 || true)
    if echo "$error_msg" | grep -q "ParameterNotFound"; then
        pass "ssm:GetParameter + kms:Decrypt (parameter not yet created, permission OK)"
    elif echo "$error_msg" | grep -q "AccessDeniedException"; then
        missing_perms+=("ssm:GetParameter or kms:Decrypt")
        fail "Missing permission: ssm:GetParameter or kms:Decrypt
       Ensure your IAM role/user has:
         - ssm:GetParameter
         - ssm:PutParameter
         - kms:Decrypt (for SecureString)"
    else
        warn "ssm:GetParameter — unexpected response, proceeding anyway"
        info "$error_msg"
    fi
fi

# ── Step 3: Get the token ──────────────────────
echo ""
echo "=== Step 3/5: GitHub token input ==="

if [[ "${1:-}" == "--token" && -n "${2:-}" ]]; then
    token="$2"
    info "Using token from --token argument"
else
    echo -n "Enter your GitHub Personal Access Token (ghp_...): "
    read -rs token
    echo ""
fi

if [[ -z "$token" ]]; then
    fail "Token cannot be empty."
fi

if [[ ! "$token" =~ ^gh[ps]_ ]]; then
    warn "Token doesn't start with 'ghp_' or 'ghs_' — are you sure this is a GitHub PAT?"
fi

pass "Token received (${#token} characters)"

# ── Step 4: Store in SSM ───────────────────────
echo ""
echo "=== Step 4/5: Storing token in SSM Parameter Store ==="

if aws ssm put-parameter \
    --name "$PARAM_NAME" \
    --type SecureString \
    --value "$token" \
    --overwrite \
    --output json >/dev/null 2>&1; then
    pass "Stored as SecureString at: $PARAM_NAME"
else
    fail "Failed to store parameter. Check your IAM permissions:
       - ssm:PutParameter
       - kms:Encrypt (for SecureString)"
fi

# ── Step 5: Verify ─────────────────────────────
echo ""
echo "=== Step 5/5: Verification ==="

# 5a: Read back from SSM
readback=$(aws ssm get-parameter \
    --name "$PARAM_NAME" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text 2>&1) || fail "Could not read back parameter from SSM."

if [[ "$readback" == "$token" ]]; then
    pass "SSM read-back matches"
else
    fail "SSM read-back does NOT match the stored token!"
fi

# 5b: Test GitHub API
echo ""
github_user=$(curl -sf -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/user 2>&1) || fail "GitHub API call failed. Is the token valid?"

username=$(echo "$github_user" | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))" 2>/dev/null)

if [[ -n "$username" ]]; then
    pass "GitHub API verified — authenticated as: $username"
else
    fail "GitHub API returned unexpected response."
fi

# ── Done ───────────────────────────────────────
echo ""
echo -e "${GREEN}=== All checks passed! ===${NC}"
echo ""
info "Token is securely stored in SSM Parameter Store."
info ""
