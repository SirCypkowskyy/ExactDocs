---
name: writing-issues
description: Use when creating, rewriting or triaging a GitHub issue for ExactDocs (feature or bug). Gives the required sections, labels and the gh commands to file it.
---

# Writing issues

Every issue is a **Feature** or a **Bug**, with the sections of `.github/ISSUE_TEMPLATE/*.yml`.
Issues describe *what* and *why*. *How* belongs in the PR (or, optionally, in Notes / Proposed fix).

## Feature

Title: `feat: <outcome in plain words>`, e.g. `feat: search refuses to answer for unindexed versions`.

```markdown
### Context
Business context: who needs it, in what situation, what it costs them today. Links.

### Expected behavior
Observable behavior after the change, from the user's or agent's side. Prefer Gherkin; it
becomes the behave scenario as-is:
Given ..., When ..., Then ...

### Criteria of success
- [ ] verifiable item (a behave scenario, a test, a metric, a visible behavior)
- [ ] ...

### Area
backend / retrieval, web UI, MCP tools, ...

### Notes
Optional: constraints, out of scope, open questions.
```

## Bug

Title: `bug: <observed symptom>`, e.g. `bug: search_docs returns 19.1 excerpts for 18.3`.

```markdown
### Context
Business context + version (image tag or `exactdocs --version`), backend (SQLite/PostgreSQL),
steps to reproduce, observed vs expected.

### Why is it bad
Impact: wrong answers to agents, data loss, security, blocked workflow, cosmetic.
Who and how often. Workaround?

### Severity
critical | major | minor | trivial

### Recommended / proposed fix
Optional: root-cause hypothesis, code involved (`path/to/file.py:42`), sketch of the fix.
```

## Rules

- One problem per issue. If the criteria of success span two domains or two releases, split it.
- Criteria must be checkable by someone who did not write the issue. "Works well" is not one.
- Never put secrets, tokens or customer data in an issue. Security bugs go to SECURITY.md, not here.
- Search first: `gh issue list --search "<keywords>" --state all`.

## Filing it

```bash
gh issue create \
  --title "feat: search refuses to answer for unindexed versions" \
  --label "type: feature" --label "status: triage" --label "area: backend" \
  --body-file /path/to/body.md
```

Use `type: bug` for bugs. New issues start in `status: triage`; a maintainer moves them to
`status: ready`. Agents may only start on `status: ready` issues (see the `claiming-issues` skill).

## Epics, sub-issues and dependencies

An **epic** is a tracking issue titled `epic: E<n> <name>` and labelled `type: epic` (no
milestone; it spans milestones); its body also holds a `- [ ] #<n>` task list of its features
as a fallback view. Every feature is linked as a GitHub **sub-issue** of its epic, and every
whole-issue "Depends on" also becomes a GitHub **blocked by** relationship (skip partial ones
such as "metrics only", "pgvector part only" or a milestone like "MVP-1"). Both APIs take the issue's
database `id`, not its number. Check the dependencies API once
(`gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by`); if it returns 404, skip
"blocked by" and rely on `Depends on #<n>` lines and the epic task list:

```bash
id() { gh api "repos/{owner}/{repo}/issues/$1" --jq .id; }
gh api repos/{owner}/{repo}/issues/<epic>/sub_issues -F sub_issue_id="$(id <feature>)"
gh api repos/{owner}/{repo}/issues/<feature>/dependencies/blocked_by -F issue_id="$(id <dependency>)"
```

File features in dependency (topological) order so each dependency already has a number. When
filing many issues, record each number (`url=$(gh issue create …); echo "<plan-id> ${url##*/}" >> filed.tsv`)
and pause about 1 s between write calls (GitHub's secondary rate limits); record epics the same
way under their epic ID (`echo "E3 ${url##*/}" >> filed.tsv`) so sub-issue links can find them.
The body file uses the form's headings (`### Context`, `### Expected behavior`, ...), as above.
Labels, including `type: epic`, are defined in `.github/labels.yml` and applied with
`.agents/skills/working-on-issues/scripts/sync-labels.sh`.

## Promoting a milestone

When a planned milestone is accepted, promote all its triaged issues at once:

```bash
gh issue list --milestone "<milestone>" --label "status: triage" --limit 200 --json number --jq '.[].number' |
  xargs -I{} gh issue edit {} --remove-label "status: triage" --add-label "status: ready"
```
