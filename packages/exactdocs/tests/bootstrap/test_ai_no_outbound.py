"""#241 socket guard: with the SDKs' environment variables set, ExactDocs reaches only what the
operator configured.

Each case runs in a fresh interpreter (imports and the guard are process-wide). The guard refuses,
and records, every connection and name lookup that is not loopback. The SDKs' variables point
to a *trap* gateway on loopback, so a call that followed them would be seen there too.

- Nothing configured: no connection at all, and nothing of the ``[ai]`` extra imported.
- A provider configured: calls reach only its own base URL, with its own key (or ``unused``),
  never a variable's value. tiktoken is never used: a chat role does not even import it; an
  OpenAI-API embedding role imports it (pydantic-ai's embeddings module does at load) but loads
  no encoding, so nothing is fetched from ``openaipublic.blob.core.windows.net``.

Identity endpoints (Google's token endpoint or metadata server, Entra ID) are not reached here:
the profiles use no Google or Entra credentials. ``test_ai_models.py`` checks those clients get
their project, location and token provider from the profile.
"""

import json
from pathlib import Path

from socket_guard import AI_MODULES, CONFIGURED, NOTHING_CONFIGURED, run_guarded


def test_nothing_configured_opens_no_connection_and_imports_nothing_of_the_ai_extra(
    tmp_path: Path,
) -> None:
    seen = run_guarded(tmp_path, NOTHING_CONFIGURED)

    assert seen["blocked"] == []
    assert seen["trap"] == 0
    loaded = set(seen["modules"])
    assert not (loaded | {m.split(".")[0] for m in loaded}) & AI_MODULES


def test_a_configured_provider_is_reached_with_its_own_values_only(tmp_path: Path) -> None:
    seen = run_guarded(tmp_path, CONFIGURED)

    assert seen["blocked"] == []
    assert seen["trap"] == 0  # no *_BASE_URL / *_ENDPOINT variable was followed
    assert seen["checks"] == [
        ["embedding", "ok", 3, None],
        ["llm", "ok", None, None],
        ["judge", "ok", None, None],
    ]
    calls = {path: (auth, key) for path, auth, key in seen["corp"]}
    assert calls["/v1/embeddings"] == ("Bearer unused", None)
    assert calls["/v1/chat/completions"] == ("Bearer unused", None)
    assert "claude-key" in str(calls["/v1/messages"])
    assert "from-the-environment" not in json.dumps(seen["corp"])
    # pydantic-ai's OpenAI embeddings module imports tiktoken when it loads; chat never loads
    # it, and no encoding is ever loaded (nothing counts tokens), so nothing is downloaded.
    assert not seen["tiktoken_after_chat"]
    assert seen["tiktoken_encodings"] == []
