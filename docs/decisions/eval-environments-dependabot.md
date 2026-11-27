# Eval environments and Dependabot

!!! abstract "TL;DR"
    - The coding tasks' environments pin one old library version each on purpose, so Dependabot
      leaves them alone: no version updates and no security updates.
    - Their security alerts are dismissed as "vulnerable code is not actually used", because the
      environments only run in the evals' offline sandbox.

| | |
|---|---|
| **Status** | Accepted, 2026-11-26 |
| **Scope** | `packages/exactdocs/evals/coding/environments/*` and `.github/dependabot.yml` |
| **Issue** | #614 (after #602) |
| **Decided by** | Proposed in #614 |

## Context

Each directory under `packages/exactdocs/evals/coding/environments/` (`zod-3.23.8`,
`pydantic-1.10.22`, `starlette-0.27.0`, ...) holds one library at one exact version. Its
`environment.yaml` names that version and lists the APIs that must not appear for it, and the
coding tasks check that the lockfile pins exactly that version (see the docstring of
`evals/coding_tasks/environments.py`). The evals measure whether an agent writes code for the
version it was given, so the old version is the point of the environment.

Dependabot's #602 moved `zod-3.23.8` to zod 4.6.6. The environment no longer matched its own
name, and the coding-tasks job and pytest failed.

## Decision

`.github/dependabot.yml` has an npm and a pip entry for those directories with
`open-pull-requests-limit: 0` and an ignore rule for every dependency. The entries set no
`target-branch`, because Dependabot applies an entry to security updates only when it has none.
Dependabot reads the file from `main`, so this takes effect with the next release.

Alerts on these lockfiles, such as GHSA-mrhx-c7xc-m3w5 on `zod-3.23.8` and `zod-4.0.17`, are
dismissed as "vulnerable code is not actually used". The packages are installed into a cache and
run only inside the evals' sandbox, which has no network.

Not verified yet: whether the ignore rule also stops security PRs. If one still arrives, it is
closed and its alert dismissed the same way.

## Considered options

- **Keep the updates and re-pin by hand** after each one, or rename the environment to the new
  version. Rejected: every bump is a red CI run and a manual revert, and a renamed environment
  stops testing the version its tasks were written for.
