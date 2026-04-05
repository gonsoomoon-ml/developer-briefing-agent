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
