"""Version-pinned coding tasks (#496): an agent's code must run against the version a project pins.

``tasks`` reads the task format (a workspace template, the prompt, hidden tests, the APIs that
must not appear for the pinned version, a reference solution and a solution written for another
version) and turns the tasks into a Pydantic Evals dataset; ``environments`` prepares each pinned
environment from its lockfile; ``sandbox`` runs a command with no network and CPU, memory and time
limits (a process sandbox or a Docker container); ``grading`` runs a workspace's hidden tests in the
sandbox and finds the forbidden APIs and the files changed; ``evaluators`` reports them;
``workspace`` gives the agent its workspace tools; ``agent`` runs a pydantic-ai agent on a task with
a documentation arm of the agent benchmark (``agent_bench``); ``offline`` holds the scripted
models; ``report`` aggregates per task, project and arm; ``cli`` is ``just coding-tasks``. See
docs/evals.md#version-pinned-coding-tasks.
"""
