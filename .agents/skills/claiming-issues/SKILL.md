---
name: claiming-issues
description: Use when an agent (or subagent) starts, pauses, hands off or finishes work on a GitHub issue. Declares ownership with a comment + labels so parallel agents never work on the same issue.
---

# Claiming issues

Several agents may work in parallel. The issue itself is the lock: **before writing any code
for an issue, claim it; when you stop, update it.** Use the scripts next to this file (they
need `gh` authenticated and `jq`).

## 1. Check it is free

```bash
.agents/skills/claiming-issues/scripts/status.sh <issue>
```

Do **not** start if any of these is true. Report back to whoever dispatched you instead:

- label `status: in progress` or `status: in review` is set, or the issue has an assignee
  (someone else owns it). A claim older than 48 h with no activity may be taken over, but only
  after commenting and @-mentioning the previous owner.
- label `status: triage` or `status: blocked` (not ready to be worked on)
- the issue is closed

## 2. Claim

```bash
.agents/skills/claiming-issues/scripts/claim.sh <issue> "<agent name>" "<branch>" "<one-line plan>"
```

This assigns the authenticated user, sets `status: in progress` + `agent`, removes
`status: ready`, and posts:

> 🤖 **Claimed by `<agent name>`**, branch `<branch>`.
> Plan: <one-line plan>
> I'll post here when a PR is open or if I stop.

`<agent name>` must identify you uniquely among parallel workers, e.g. `claude/subagent-retrieval-1`.
Then **re-run `status.sh`**: if another claim comment landed before yours, the earliest one wins
and you must release (step 4).

## 3. Report progress (only when it matters)

Comment when you hit a decision the issue author should know about, a scope change, or a blocker
(then also add `status: blocked` with `gh issue edit <n> --add-label "status: blocked"`).
No routine "still working" comments.

## 4. Finish or release

PR opened (the PR body contains `Closes #<issue>`):

```bash
.agents/skills/claiming-issues/scripts/handoff.sh <issue> review "<PR url>" "<what was done, how it was tested>"
```

Stopping without a PR (blocked, out of scope, lost the race, or interrupted):

```bash
.agents/skills/claiming-issues/scripts/handoff.sh <issue> release "" "<why, what is left, where the branch is>"
```

`review` sets `status: in review`. `release` puts the issue back to `status: ready` (or
`status: blocked` if you set it) and unassigns. Both remove `agent`.
Never leave an issue in `status: in progress` when you stop.
