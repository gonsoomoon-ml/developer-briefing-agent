---
name: alex
description: Alex's standup format and preferences
allowed-tools:
  - shell
  - file_read
---

## 스탠드업 형식
Format: 3 bullets max. 이번 주 한 일 / 오늘 할 일 / 블로커.
Alex's team lead cares most about blockers — always lead with those if any exist.
Skip routine commits. Only mention PRs and code reviews.
Keep each bullet under 15 words.

## GitHub 데이터 수집

스킬 디렉토리에서 아래 명령어로 데이터를 수집하세요:

```bash
python {skill_dir}/scripts/github_standup.py \
  --repos aws-samples/sample-deep-insight \
           gonsoomoon-ml/analyze-claude-code \
           gonsoomoon-ml/bedrock-cost-guardrail \
           gonsoomoon-ml/claude-extensions \
  --days 7 \
  --output /tmp/standup_data.json
```

수집 후 file_read로 `/tmp/standup_data.json`을 읽어 스탠드업을 작성하세요.
maintainer로서 본인이 작성하지 않은 오픈 PR도 리뷰 대상입니다.
