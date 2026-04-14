"""
demo_flow_test.py — docs/demo/demo-script.md 6-Act 비디오 흐름 자동 테스트

각 Act를 비대화형으로 실행하고 출력을 검증합니다.
LLM 출력은 비결정적이므로 (1) exit code 0, (2) 핵심 키워드 grep,
(3) 최소 출력 길이 세 가지로 assertion 합니다.

사용법:
    uv run tests/demo_flow_test.py
    uv run tests/demo_flow_test.py --skip-act6   # 원격 호출 스킵
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(f"/tmp/demo_test_{int(time.time())}")
LOG_DIR.mkdir(parents=True, exist_ok=True)

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"

results = []


def run(cmd, env_extra=None, stdin_input=None, timeout=180, log_name="run"):
    """서브프로세스 실행, stdout/stderr 캡처, 로그 파일에 저장."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    log_path = LOG_DIR / f"{log_name}.log"
    print(f"{DIM}    $ {' '.join(cmd)}{NC}")
    print(f"{DIM}    log: {log_path}{NC}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        log_path.write_text(f"TIMEOUT after {timeout}s\n\nstdout:\n{e.stdout or ''}\n\nstderr:\n{e.stderr or ''}")
        return -1, e.stdout or "", e.stderr or ""
    log_path.write_text(
        f"exit={proc.returncode}\n\n=== STDOUT ===\n{proc.stdout}\n\n=== STDERR ===\n{proc.stderr}"
    )
    return proc.returncode, proc.stdout, proc.stderr


def assert_act(name, exit_code, stdout, *, must_contain=(), min_len=200, allow_any_of=None):
    """Act 결과 평가."""
    failures = []
    if exit_code != 0:
        failures.append(f"exit={exit_code} (expected 0)")
    if len(stdout) < min_len:
        failures.append(f"output too short: {len(stdout)} chars (min {min_len})")
    for kw in must_contain:
        if kw not in stdout:
            failures.append(f"missing keyword: {kw!r}")
    if allow_any_of:
        if not any(kw in stdout for kw in allow_any_of):
            failures.append(f"none of any-of keywords found: {allow_any_of}")
    status = "PASS" if not failures else "FAIL"
    color = GREEN if status == "PASS" else RED
    print(f"  {color}[{status}]{NC} {name}")
    for f in failures:
        print(f"    {RED}- {f}{NC}")
    results.append((name, status, failures))
    return status == "PASS"


def banner(text):
    print(f"\n{CYAN}{'='*60}{NC}")
    print(f"{CYAN}  {text}{NC}")
    print(f"{CYAN}{'='*60}{NC}")


def precheck():
    banner("사전 점검")
    env_path = PROJECT_ROOT / "local-agent" / ".env"
    if not env_path.exists():
        print(f"  {RED}[FAIL]{NC} {env_path} 없음")
        sys.exit(1)
    print(f"  {GREEN}[OK]{NC} {env_path} 존재")

    skill_sejong = PROJECT_ROOT / "skills" / "sejong" / "SKILL.md"
    skill_sunshin = PROJECT_ROOT / "skills" / "sunshin" / "SKILL.md"
    for p in (skill_sejong, skill_sunshin):
        if not p.exists():
            print(f"  {RED}[FAIL]{NC} {p} 없음")
            sys.exit(1)
        print(f"  {GREEN}[OK]{NC} {p} 존재")

    env_text = env_path.read_text()
    has_memory = "MEMORY_ID=" in env_text and not env_text.strip().endswith("MEMORY_ID=")
    print(f"  {DIM}MEMORY_ID present: {has_memory}{NC}")
    return has_memory


def act1_single_shot():
    banner("Act 1: example_single_shot.py (sejong 기본)")
    code, out, err = run(
        ["uv", "run", "local-agent/example_single_shot.py"],
        env_extra={"DEV_NAME": "sejong"},
        timeout=300,
        log_name="act1_sejong",
    )
    assert_act(
        "Act 1 — sejong 단발 실행",
        code, out,
        allow_any_of=["커밋", "PR", "블로커", "이슈", "오늘"],
        min_len=200,
    )


def act2_skill_check():
    banner("Act 2: SKILL.md 형식 검증")
    sejong = (PROJECT_ROOT / "skills" / "sejong" / "SKILL.md").read_text()
    sunshin = (PROJECT_ROOT / "skills" / "sunshin" / "SKILL.md").read_text()
    pass1 = "analyze-claude-code" in sejong or "developer-briefing-agent" in sejong
    pass2 = "sample-deep-insight" in sunshin or "claude-extensions" in sunshin
    status1 = "PASS" if pass1 else "FAIL"
    status2 = "PASS" if pass2 else "FAIL"
    print(f"  {(GREEN if pass1 else RED)}[{status1}]{NC} Sejong SKILL — repo 명시")
    print(f"  {(GREEN if pass2 else RED)}[{status2}]{NC} Sunshin SKILL — repo 명시")
    results.append(("Act 2 — sejong SKILL repos", status1, []))
    results.append(("Act 2 — sunshin SKILL repos", status2, []))


def act3_chat_sejong():
    banner("Act 3: chat.py 비대화형 (sejong)")
    code, out, err = run(
        ["uv", "run", "local-agent/chat.py", "--dev_name", "sejong"],
        stdin_input="오늘 업무 브리핑 해줘\n/quit\n",
        timeout=300,
        log_name="act3_sejong_chat",
    )
    assert_act(
        "Act 3 — sejong chat",
        code, out,
        must_contain=["sejong"],
        allow_any_of=["커밋", "PR", "블로커", "이슈"],
        min_len=200,
    )


def act4_sunshin():
    banner("Act 4: example_single_shot.py (sunshin) — 개인화 차이")
    code, out, err = run(
        ["uv", "run", "local-agent/example_single_shot.py"],
        env_extra={"DEV_NAME": "sunshin"},
        timeout=300,
        log_name="act4_sunshin",
    )
    # Sunshin 형식: 번호 목록 (1./2./3.) — exact 매치는 어려우니 키워드/길이만
    assert_act(
        "Act 4 — sunshin 단발 실행",
        code, out,
        allow_any_of=["sample-deep-insight", "claude-extensions", "PR", "shipped", "building"],
        min_len=200,
    )


def act5_memory(has_memory):
    banner("Act 5: 크로스 세션 메모리")
    if not has_memory:
        print(f"  {YELLOW}[SKIP]{NC} MEMORY_ID 미설정 — 크로스 세션 검증 불가")
        results.append(("Act 5 — 크로스 세션 메모리", "SKIP", []))
        return

    # 세션 1: 특정 PR 번호 언급하는 질문
    code1, out1, _ = run(
        ["uv", "run", "local-agent/chat.py", "--dev_name", "sunshin"],
        stdin_input="리뷰할 PR 있어?\n/quit\n",
        timeout=300,
        log_name="act5_session1",
    )
    pass1 = code1 == 0 and len(out1) > 200
    print(f"  {(GREEN if pass1 else RED)}[{'PASS' if pass1 else 'FAIL'}]{NC} 세션 1: PR 질문 — exit={code1}, len={len(out1)}")

    # 잠시 대기 (메모리 저장 시간)
    time.sleep(5)

    # 세션 2: 이전 세션 참조
    code2, out2, _ = run(
        ["uv", "run", "local-agent/chat.py", "--dev_name", "sunshin"],
        stdin_input="아까 얘기한 PR 어떻게 됐어?\n/quit\n",
        timeout=300,
        log_name="act5_session2",
    )
    # 메모리가 작동하면 응답에 PR 관련 컨텍스트가 포함되어야 함
    has_pr_context = any(kw in out2 for kw in ["PR", "#", "리뷰", "이전", "지난"])
    pass2 = code2 == 0 and len(out2) > 200 and has_pr_context
    print(f"  {(GREEN if pass2 else RED)}[{'PASS' if pass2 else 'FAIL'}]{NC} 세션 2: 이전 컨텍스트 회상 — pr_context={has_pr_context}")

    status = "PASS" if (pass1 and pass2) else "FAIL"
    results.append(("Act 5 — 크로스 세션 메모리", status, [] if status == "PASS" else ["see act5_session*.log"]))


def act6_remote(skip):
    banner("Act 6: AgentCore Runtime 원격 호출")
    if skip:
        print(f"  {YELLOW}[SKIP]{NC} --skip-act6 지정")
        results.append(("Act 6 — 원격 runtime 호출", "SKIP", []))
        return
    code, out, err = run(
        ["uv", "run", "managed-agentcore/example_invoke.py", "--dev_name", "sunshin"],
        timeout=300,
        log_name="act6_remote_sunshin",
    )
    assert_act(
        "Act 6 — example_invoke (sunshin)",
        code, out,
        allow_any_of=["PR", "커밋", "오늘", "shipped", "building"],
        min_len=100,
    )


def summary():
    banner("결과 요약")
    pass_count = sum(1 for _, s, _ in results if s == "PASS")
    fail_count = sum(1 for _, s, _ in results if s == "FAIL")
    skip_count = sum(1 for _, s, _ in results if s == "SKIP")
    for name, status, failures in results:
        color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[status]
        print(f"  {color}[{status}]{NC} {name}")
    print(f"\n  Total: {len(results)}  {GREEN}PASS={pass_count}{NC}  {RED}FAIL={fail_count}{NC}  {YELLOW}SKIP={skip_count}{NC}")
    print(f"  Logs: {LOG_DIR}")
    return fail_count == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-act6", action="store_true", help="Act 6 (원격 호출) 스킵")
    parser.add_argument("--skip-memory", action="store_true", help="Act 5 (메모리) 스킵")
    args = parser.parse_args()

    has_memory = precheck()
    if args.skip_memory:
        has_memory = False

    act1_single_shot()
    act2_skill_check()
    act3_chat_sejong()
    act4_sunshin()
    act5_memory(has_memory)
    act6_remote(args.skip_act6)

    ok = summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
