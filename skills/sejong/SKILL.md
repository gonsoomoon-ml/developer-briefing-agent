---
name: sejong
description: Daily standup for Sejong — GitHub activity based, 3 bullets format
allowed-tools:
  - shell
  - file_read
---

## 담당 저장소
- `gonsoomoon-ml/developer-briefing-agent` — 개발자 브리핑 에이전트
- `gonsoomoon-ml/analyze-claude-code` — Claude Code 소스 분석


## 스탠드업 형식
Format: 3 bullets max. 이번 주 한 일 / 오늘 할 일 / 블로커.
Sejong's team lead cares most about blockers — always lead with those if any exist.
Skip routine commits. Only mention PRs and code reviews.
Keep each bullet under 15 words.

## GitHub 데이터 수집

스킬 디렉토리에서 아래 명령어로 데이터를 수집하세요:

```bash
python {skill_dir}/scripts/github_standup.py \
  --repos gonsoomoon-ml/analyze-claude-code \
           gonsoomoon-ml/developer-briefing-agent \
  --days 7 \
  --output /tmp/standup_data.json
```

수집 후 file_read로 `/tmp/standup_data.json`을 읽어 스탠드업을 작성하세요.
maintainer로서 본인이 작성하지 않은 오픈 PR도 리뷰 대상입니다.
