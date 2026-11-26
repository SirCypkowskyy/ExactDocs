# Adding libraries from an agent

!!! abstract "TL;DR"
    - `add_docs(source, ref?, paths?)` queues the import of a library or of one version of it, and
      `import_status(job_id?)` follows the imports.
    - Only callers who may create libraries see them: instance admins, and the users and groups of
      `[auth.library_creation]` once it is set (unset, every signed-in user may create libraries).
      Everyone else gets them neither listed nor callable.
    - Sources are `https://` URLs on the hosts of `EXACTDOCS_MCP_IMPORT_HOSTS`, `owner/repo` on
      GitHub, or a library that is already indexed. Nothing over MCP removes anything.

An agent that finds a library missing or stale can add it without its user leaving the agent
(#613). Both tools queue work through the same use cases as `POST /api/v1/libraries`,
`POST .../versions` and `POST .../sync`, under the same permission checks, so an import queued
from an agent is recorded as its user's (`created_by`, and a new library's `library_created`
entry in the access log). The job list shows it came over MCP.

| Tool | What it does |
|---|---|
| `add_docs(source, ref?, paths?)` | A new repository becomes a library (with the paths of its `context7.json`, unless `paths` is given); a `ref` of an indexed library becomes a version; no `ref` re-syncs the library's moved branches |
| `import_status(job_id?)` | One line for the job: its state, the files done of the total, and the error code if it failed<br/>Without a job ID, the caller's five latest jobs |

## Who sees them

The tools carry FastMCP's component-level `auth`: on every request, the server runs the same
creation check as `POST /api/v1/libraries` for the caller of the request's API token or OAuth
token. A caller who fails it does not find the tools in `tools/list`, and a call by name answers
as for a tool that does not exist. So someone who loses the permission stops seeing them on
their next request, and an agent without it spends no tokens on their schemas.

- **Instance admins** always pass.
- **The users and the members of the groups of `[auth.library_creation]`** pass (see
  [Who may create libraries](../configuration/sign-in/index.md#who-may-create-libraries)). Without
  that section every signed-in user may create libraries, and so gets the tools: set it to keep
  them to a few people.
- **A token limited to some libraries** never passes, even an admin's: it may not create a library
  it does not name.
- **stdio** (`serve --stdio`) and in-process clients without a token never get them.

## What `add_docs` takes

`source` is one of:

- an `https://` git URL, such as `https://gitlab.com/group/docs`;
- `owner/repo`, read as `https://github.com/owner/repo`;
- the ID (`/owner/repo`) or name of a library already indexed.

| Source and `ref` | What happens | Answer |
|---|---|---|
| A repository no library has, any `ref` | The library is created and its import queued (no `ref`: the default branch) | `queued /fastapi/fastapi@master (a1b2c3d), job <id>` |
| An indexed library and a new `ref` | The version is queued, with the library's own settings | `queued /fastapi/fastapi@0.115.0 (a1b2c3d), job <id>` |
| An indexed library and a `ref` it has | Nothing is queued | `already indexed: /fastapi/fastapi@0.115.0 (a1b2c3d)` |
| A `ref` whose import is queued or running | Nothing is queued | `already importing: /fastapi/fastapi@0.115.0, job <id> (running)` |
| An indexed library and no `ref` | Its moved branches are queued, as a sync | one line per version: `master: queued, job <id>` |

A `ref` that differs from a tag only by a leading `v` (`0.115.0` for `v0.115.0`) is read as that
tag. `paths` (at most 20 globs) applies to a new library only; change an indexed library's paths
in the web UI. Each answer starts with the notice that ref names and other repository text are
untrusted data.

## Which sources are refused

Arguments of an agent can come from a prompt injection in docs it read, so the source is checked
before git runs, and the answer is `source_not_allowed: <why>`:

- any scheme but `https://`: `http://`, `ssh://` (its host key needs a person to confirm it),
  `git@host:path`, `file://` and git's transport helpers;
- a URL with credentials, a query, or a port other than 443;
- a host not in `EXACTDOCS_MCP_IMPORT_HOSTS`;
- a host name that does not resolve, or resolves to any loopback, private, shared, link-local
  (the cloud metadata endpoints), unique-local or otherwise non-public address. The name is
  resolved when the call is made, not when the setting is read.

A URL whose library ID belongs to a library of another repository is refused with
`library_exists`, naming that library; nothing is overwritten. There is no credential argument:
private repositories are added in the web UI, so no secret passes through an agent's context.
The import limits are those of every import, and a busy preview answers
`preview_busy: try again in N s`.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_MCP_IMPORT_HOSTS` | `github.com,gitlab.com,codeberg.org,bitbucket.org` | The hosts `add_docs` may import from, comma-separated, exact names.<br/>Empty: `add_docs` takes no URL, and only adds versions to and re-syncs libraries already indexed |

!!! note "The address check and later fetches"
    The address check runs at the call, right before git asks the host for its refs. The import
    job fetches later from the same host, and the next scheduled sync again, without a new check:
    the allowlist is what keeps those fetches on public forges. git also follows an HTTP redirect
    on its first request, as for any import, so a host of the allowlist could send it elsewhere. Add a host of your own network to
    `EXACTDOCS_MCP_IMPORT_HOSTS` only if its name resolves to a public address, or add its
    libraries in the web UI instead. Behind a proxy that resolves names for the server, a host the
    server cannot resolve itself is refused.

## What is not over MCP

Removing libraries or versions, cancelling jobs, editing library settings, tag rules, chunking and
credentials stay in the web UI and REST. Removal is destructive, and it is the action a prompt
injection would aim for. See [the decision record](../decisions/mcp-write-tools.md).
