---
name: maria
description: Maria's standup format and preferences
allowed-tools:
  - shell
  - file_read
---

## 스탠드업 형식
Format: numbered list. What I shipped / What I'm building / What I need.
Always include "What I need" even if nothing is blocked — write "nothing blocked".
Always include PR links when mentioning pull requests.
Maria's lead wants detail — 2 sentences per item is fine.

## GitHub 데이터 수집

스킬 디렉토리에서 아래 명령어로 데이터를 수집하세요:

```bash
python {skill_dir}/scripts/github_standup.py \
  --repos aws-samples/sample-deep-insight \
           gonsoomoon-ml/claude-extensions \
           gonsoomoon-ml/developer-briefing-agent \
  --days 7 \
  --output /tmp/standup_data.json
```

수집 후 file_read로 `/tmp/standup_data.json`을 읽어 스탠드업을 작성하세요.
maintainer로서 본인이 작성하지 않은 오픈 PR도 리뷰 대상입니다.
