# Demo Idea: Daily Developer Briefing Agent

## Core Concept
A scheduled agent service that delivers a personalized briefing to each developer every morning — using their own GitHub, Jira, and Calendar credentials. Gets smarter about each person over time via memory. Serves the whole team simultaneously.

## Why Claude Code Can't Do This
- Runs on a schedule — no human triggers it
- Each user has their own OAuth credentials (3-legged OAuth)
- Memory is per-user, accumulates over weeks
- Serves multiple developers simultaneously as a deployed service

## Two Modes

### Individual Briefing
```
Good morning Alex. Here's your day:

Meetings    : 2 (standup 10am, arch review 2pm)
PRs to review: 3 (2 urgent — CI is blocking the team)
Your tickets : sprint ends Thursday, 2 still in-progress
Deployment  : your last PR merged, staging deploy succeeded overnight
```

### Team Briefing (for lead/manager)
```
Team status this morning:

Blocked : Maria's PR has been waiting review for 2 days
OOO     : Jake is out today
At risk : 4 tickets unfinished, 2 days left in sprint
Deploy  : 3 PRs merged yesterday, production deploy scheduled today
```

## Memory — What Makes It Better Over Time
- Week 1: generic format, all fields shown
- Week 3: learns "Alex ignores ticket counts, cares only about blocked PRs"
- Week 6: learns "team always has deploy risk on Thursdays — flag proactively"

## Live Demo Flow (5 min)
1. Show agent code — minimal Strands lines
2. Show AgentCore Gateway: GitHub + Jira + Calendar connected as MCP tools
3. Trigger manual run → briefing appears in Slack for Developer A
4. Trigger for Developer B → different data, different format (their own OAuth)
5. Show memory panel — what the agent has learned about each person

## Capabilities Showcased

| Strands Agents SDK | Amazon Bedrock AgentCore |
|--------------------|--------------------------|
| Tool orchestration | Gateway: GitHub + Jira + Calendar as MCP tools |
| Structured output generation | Memory: per-user preferences, cross-session |
| Multi-agent (individual + team views) | Runtime: scheduled, always-on service |
| | Identity: per-user 3LO OAuth tokens |
| | Observability: trace each morning's run |

---

## Additional Briefing Variants

### B1. On-Call Handoff Briefing
Triggered when on-call rotation changes. New on-call person gets full system context: open alerts, recent incidents, known risks, last deploy status. Memory tracks incident history and patterns over time.

### B2. Sprint Retrospective Briefing
Auto-generated at sprint end. Shows completion rate, rolled-over tickets, PR review time trends, top blockers. Memory surfaces multi-sprint patterns humans miss (e.g. same ticket rolling over 3 sprints).

### B3. Release Readiness Briefing ← strongest candidate
Before every planned release: go/no-go checklist. Tests, docs, rollback plan, deploy-day risk (e.g. "last 2 Friday releases caused incidents"). Memory learns what this specific team consistently misses.

### B4. Security & Dependency Briefing
Weekly scan of team's repos. New CVEs mapped to affected services, stale dependencies, unaddressed items from last week. Memory tracks acknowledgement vs. action per CVE.

### B5. Team Health Briefing *(for leads)*
Weekly DORA-style signals: deploy frequency, PR wait times, build failure rate, at-risk developers. Memory establishes per-team baseline and flags deviations — not raw numbers.
