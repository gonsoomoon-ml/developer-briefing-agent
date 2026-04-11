---
name: sunshin
description: Daily standup for Sunshin — GitHub activity based, numbered list format
allowed-tools:
  - shell
  - file_read
---

## 담당 저장소
- `aws-samples/sample-deep-insight` — 데이터 분석 인사이트 샘플
- `gonsoomoon-ml/claude-extensions` — Claude 확장 기능

## 스탠드업 형식
Format: numbered list. What I shipped / What I'm building / What I need.
Always include "What I need" even if nothing is blocked — write "nothing blocked".
Always include PR links when mentioning pull requests.
Sunshin's lead wants detail — 2 sentences per item is fine.

## PR 리뷰 처리 규칙 (dependabot 포함)

오픈 PR이 많을 때는 다음 우선순위로 정리하세요:

1. **사람이 작성한 PR** — 항상 개별 항목으로 상세히 표시 (작성자, 목적, 리뷰 상태)
2. **⚠️ 위험 dependabot PR** — 개별 항목으로 표시하고 이유 명시:
   - Major 버전 점프 (예: `1.1.x → 1.2.x` 이상) — breaking change 위험
   - 보안 민감 패키지 (`cryptography`, `pyjwt`, `requests`, `urllib3`, `langchain-core`, `langchain`)
3. **일반 dependabot PR** — minor/patch 업데이트는 개별 나열하지 말고 집계:
   - `📦 Routine dependency updates: N open (streamlit, tornado, orjson, ...)`
   - 사용자가 명시적으로 "dependabot 전부 보여줘"라고 요청할 때만 전체 목록 펼침

**출력 예시:**
```
### What I need (PR reviews)
1. #45 (jesamkim) CloudFront + Cognito 배포 옵션 — merge 대기
2. ⚠️ #47 langchain-core 1.1.3 → 1.2.28 (dependabot) — major bump, breaking change 검토 필요
3. ⚠️ #46 cryptography 46.0.3 → 46.0.7 (dependabot) — 보안 패키지
4. 📦 Routine dependency updates: 22 open (streamlit, tornado, pyjwt, orjson, ...)
```

이 규칙은 PR 수가 10개 이상일 때 적용하세요. 10개 미만이면 모두 개별 항목으로 표시해도 됩니다.

## GitHub 데이터 수집

스킬 디렉토리에서 아래 명령어로 데이터를 수집하세요:

```bash
python {skill_dir}/scripts/github_standup.py \
  --repos aws-samples/sample-deep-insight \
           gonsoomoon-ml/claude-extensions \
  --days 7 \
  --output /tmp/standup_data.json
```

수집 후 file_read로 `/tmp/standup_data.json`을 읽어 스탠드업을 작성하세요.
maintainer로서 본인이 작성하지 않은 오픈 PR도 리뷰 대상입니다.
