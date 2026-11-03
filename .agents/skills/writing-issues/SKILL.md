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
