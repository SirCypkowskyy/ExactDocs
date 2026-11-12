"""#245: local models run in this process, from the models directory, and never download.

The models are tiny stand-ins (``tiny_models``) run by the real fastembed and ONNX Runtime; the
default models run in CI's ``[local]`` eval job and in ``test_local_models_real.py``.
"""

import json
import logging
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

import tiny_models
from exactdocs.bootstrap import cli, local_models
from exactdocs.bootstrap.ai_models import (
    AiEmbeddingModels,
    AiModels,
    ConfiguredAi,
    configured_ai,
)
from exactdocs.bootstrap.constants import LOCAL_EXTRA, MODEL_MARKER
from exactdocs.bootstrap.container import Container, _rerank_limits, _warn_undeclared_local
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.bootstrap.models_pull import pull
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.local_models import LocalEmbedder
from exactdocs.retrieval.adapters.driven.sqlite import SqliteSpendLedger
from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult
from exactdocs.retrieval.errors import ProviderUnsupportedError
from exactdocs.retrieval.models import (
    ModelRole,
    ProfileOrigin,
    ProviderKind,
    ProviderProfile,
    SpendEntry,
    SpendWindow,
)
from fixture_import import LIBRARY, embed_fixture, import_fixture
from fixture_repo import DocsRepo
from retrieval_eval.fixture import instance_spend
from socket_guard import run_guarded

OFFLINE = ProviderProfile(
    name="offline", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION
)
EMBEDDING, RERANKER = tiny_models.TINY_EMBEDDING, tiny_models.TINY_RERANKER


@pytest.fixture(scope="module")
def models_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tiny_models.register()
    return tiny_models.install(tmp_path_factory.mktemp("models"))


# ---------------------------------------------------------------- what is missing, said at start


def test_a_model_that_was_not_pulled_names_the_pull_command(tmp_path: Path) -> None:
    reason = LocalModels(models_dir=tmp_path).missing("BAAI/bge-small-en-v1.5", ModelRole.EMBEDDING)

    assert reason is not None
    assert "`exactdocs models pull BAAI/bge-small-en-v1.5`" in reason
    assert "never downloaded" in reason


def test_a_model_serves_only_the_role_it_was_pulled_for(models_dir: Path) -> None:
    local = LocalModels(models_dir=models_dir)

    assert local.missing(EMBEDDING, ModelRole.EMBEDDING) is None
    assert local.missing(EMBEDDING, ModelRole.RERANKER) == (
        f"{EMBEDDING} was pulled for the embedding role, not the reranker role"
    )
    assert "embedding and reranker models only" in str(local.missing(EMBEDDING, ModelRole.LLM))


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "a/../../b", "a/b/c"])
def test_a_name_that_could_leave_the_models_directory_is_refused(tmp_path: Path, name: str) -> None:
    assert "is not a model name" in str(
        LocalModels(models_dir=tmp_path).missing(name, ModelRole.EMBEDDING)
    )


def test_without_the_local_extra_a_local_profile_says_what_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_models, "_installed", lambda module: module != "fastembed")

    assert LocalModels(models_dir=tmp_path).unsupported(OFFLINE) == LOCAL_EXTRA
    assert AiModels(local=LocalModels(models_dir=tmp_path)).unsupported(OFFLINE) == LOCAL_EXTRA


async def test_a_local_profile_runs_no_chat_model(models_dir: Path) -> None:
    with pytest.raises(ProviderUnsupportedError, match="use the ollama kind"):
        await AiModels(local=LocalModels(models_dir=models_dir)).chat_model(OFFLINE, "llama3")


# ---------------------------------------------------------------- running the models


async def test_embedding_and_rerank_run_on_the_pulled_models(models_dir: Path) -> None:
    factory = AiModels(local=LocalModels(models_dir=models_dir))

    handle = await factory.embedder(OFFLINE, EMBEDDING)
    embeddings = AiEmbeddingModels().bind(
        handle, name=f"offline:{EMBEDDING}", dimensions=None, batch_size=8
    )
    documents = await embeddings.embed_documents(["retry policy backoff", "rotate the tokens"])
    query = await embeddings.embed_query("retry backoff")
    reranker = await factory.reranker(OFFLINE, RERANKER)
    scores = await reranker.rerank(
        "how do I retry failed calls",
        ["rotate the tokens", "the retry policy repeats failed calls"],
    )

    assert await embeddings.dimensions() == tiny_models.EMBEDDING_DIMENSIONS
    assert [len(v) for v in documents.vectors] == [tiny_models.EMBEDDING_DIMENSIONS] * 2
    assert documents.input_tokens > 0
    similarity = [
        sum(a * b for a, b in zip(query.vectors[0], v, strict=True)) for v in documents.vectors
    ]
    assert similarity[0] > similarity[1]  # the shared words count
    assert scores[1] > scores[0]


async def test_a_model_is_loaded_once_per_process(models_dir: Path) -> None:
    local = LocalModels(models_dir=models_dir)

    first = await local.embedder(OFFLINE, EMBEDDING)
    again = await local.embedder(OFFLINE, EMBEDDING)

    assert isinstance(first, LocalEmbedder)
    assert isinstance(again, LocalEmbedder)
    assert again.model is first.model
    assert again.executor is first.executor


async def test_a_check_loads_the_model_and_calls_it(models_dir: Path) -> None:
    local = LocalModels(models_dir=models_dir)

    embedding = await local.check(OFFLINE, EMBEDDING, ModelRole.EMBEDDING)
    rerank = await local.check(OFFLINE, RERANKER, ModelRole.RERANKER)
    missing = await local.check(OFFLINE, "BAAI/bge-small-en-v1.5", ModelRole.EMBEDDING)

    assert (embedding.ok, embedding.dimensions, embedding.served_model) == (
        True,
        tiny_models.EMBEDDING_DIMENSIONS,
        EMBEDDING,
    )
    assert rerank.ok
    assert not missing.ok
    assert "exactdocs models pull" in str(missing.error)


async def test_a_damaged_model_says_to_pull_it_again(models_dir: Path, tmp_path: Path) -> None:
    shutil.copytree(models_dir, tmp_path / "models")
    (tmp_path / "models" / EMBEDDING / "model.onnx").write_bytes(b"not onnx")

    with pytest.raises(ProviderUnsupportedError, match=r"cannot be loaded .*pull .* again"):
        await LocalModels(models_dir=tmp_path / "models").embedder(OFFLINE, EMBEDDING)


GUARDED_LOCAL = """
import asyncio
from pathlib import Path
import tiny_models
from exactdocs.bootstrap.local_models import LocalModels
from exactdocs.retrieval.adapters.driven.local_models import LocalEmbeddingModels
from exactdocs.retrieval.models import ProfileOrigin, ProviderKind, ProviderProfile

async def main():
    models_dir = tiny_models.install(Path(os.environ["EXACTDOCS_DATA_DIR"]) / "models")
    tiny_models.register()
    local = LocalModels(models_dir=models_dir)
    profile = ProviderProfile(
        name="offline", kind=ProviderKind.LOCAL, origin=ProfileOrigin.CONFIGURATION
    )
    handle = await local.embedder(profile, tiny_models.TINY_EMBEDDING)
    embeddings = LocalEmbeddingModels().bind(
        handle, name="offline:x", dimensions=None, batch_size=4
    )
    vectors = (await embeddings.embed_documents(["retry policy", "rotate tokens"])).vectors
    query = (await embeddings.embed_query("retry")).vectors
    reranker = await local.reranker(profile, tiny_models.TINY_RERANKER)
    scores = await reranker.rerank("retry failed calls", ["retry policy", "rotate tokens"])
    return len(vectors), len(query), list(scores)

documents, queries, scores = asyncio.run(main())
print(json.dumps({
    "blocked": blocked,
    "trap": len(trap.seen),
    "documents": documents,
    "queries": queries,
    "scores": scores,
    "offline": os.environ.get("HF_HUB_OFFLINE"),
    "modules": sorted(sys.modules),
}))
"""


def test_with_sockets_blocked_embedding_and_rerank_run_on_a_tiny_model(tmp_path: Path) -> None:
    seen = run_guarded(tmp_path, GUARDED_LOCAL)

    assert seen["blocked"] == []  # no connection, no name lookup: not even to the Hub
    assert seen["trap"] == 0
    assert (seen["documents"], seen["queries"]) == (2, 1)
    assert seen["scores"][0] > seen["scores"][1]
    # No HF_HUB_OFFLINE: the model's own folder (specific_model_path, local_files_only) keeps
    # fastembed away from the Hub, as the empty `blocked` shows.
    assert seen["offline"] is None
    assert "fastembed" in seen["modules"]
    assert "onnxruntime" in seen["modules"]


# ---------------------------------------------------------------- start: a missing model


GUARDED_START = """
import asyncio, logging
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings

messages = []
class Keep(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())
logging.getLogger("exactdocs").addHandler(Keep())

async def main():
    ai = AiSettings.model_validate({
        "providers": {"local": {"kind": "local"}},
        "embedding": {"model": "local:BAAI/bge-small-en-v1.5"},
    })
    container = Container.build(Settings(ai=ai))
    async with container.running(jobs=False):
        modes = await container.retrieval.check_roles()
        return [c.role for c in modes.checks]

roles = asyncio.run(main())
print(json.dumps({
    "blocked": blocked,
    "roles": roles,
    "messages": messages,
    "modules": sorted(sys.modules),
}))
"""


def test_a_missing_model_turns_its_role_off_at_start_without_any_connection(
    tmp_path: Path,
) -> None:
    seen = run_guarded(tmp_path, GUARDED_START)

    assert seen["blocked"] == []
    assert seen["roles"] == []  # the embedding role is off: nothing to check
    [message] = [m for m in seen["messages"] if "is off" in m]
    assert "AI role embedding (local:BAAI/bge-small-en-v1.5) is off" in message
    assert "`exactdocs models pull BAAI/bge-small-en-v1.5`" in message
    assert not {"fastembed", "onnxruntime", "huggingface_hub"} & {
        m.split(".")[0] for m in seen["modules"]
    }


def test_a_pulled_model_keeps_its_role_and_is_loaded_at_start(
    models_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ai = AiSettings.model_validate(
        {
            "providers": {"offline": {"kind": "local"}},
            "embedding": {"model": f"offline:{EMBEDDING}"},
            "reranker": {"model": f"offline:{RERANKER}"},
        }
    )
    settings = Settings(data_dir=tmp_path, models_dir=models_dir, ai=ai)

    container = Container.build(settings)
    roles = [(p.name, role, model) for p, role, model in container.local_roles]

    assert roles == [
        ("offline", ModelRole.EMBEDDING, EMBEDDING),
        ("offline", ModelRole.RERANKER, RERANKER),
    ]
    assert not [r for r in caplog.records if "is off" in r.getMessage()]


def test_the_models_directory_defaults_to_the_data_directory(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path).effective_models_dir == tmp_path / "models"
    assert Settings(data_dir=tmp_path, models_dir="/opt/m").effective_models_dir == Path("/opt/m")
    assert Settings(data_dir=tmp_path, models_dir=" ").effective_models_dir == tmp_path / "models"


# ---------------------------------------------------------------- exactdocs models pull


class FakeHub:
    """Serves the tiny models' files as the Hub would (other repositories: placeholder files),
    and records every download with the revision it asked for."""

    def __init__(self, source: Path, *, drop: str | None = None) -> None:
        self.source, self.drop = source, drop
        self.downloads: list[tuple[str, list[str], str | None]] = []

    def __call__(
        self, repository: str, files: Sequence[str], folder: Path, revision: str | None
    ) -> str:
        self.downloads.append((repository, list(files), revision))
        if (self.source / repository).is_dir():
            shutil.copytree(self.source / repository, folder, dirs_exist_ok=True)
            (folder / MODEL_MARKER).unlink()  # the Hub has no marker: pull writes it
        else:
            for name in files:
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(b"placeholder")
        (folder / ".cache").mkdir()
        if self.drop:
            (folder / self.drop).unlink()
        return revision or "f" * 40  # main's commit when none was asked for


def test_pull_stores_a_model_with_its_marker_and_skips_it_the_next_time(
    models_dir: Path, tmp_path: Path
) -> None:
    hub = FakeHub(models_dir)

    first = pull([EMBEDDING, RERANKER], tmp_path, download=hub)
    second = pull([EMBEDDING], tmp_path, download=hub)

    assert [(p.ok, p.message.split()[0]) for p in first] == [(True, "pulled"), (True, "pulled")]
    assert [(p.ok, p.message.split()[0]) for p in second] == [(True, "already")]
    assert [(repository, revision) for repository, _, revision in hub.downloads] == [
        (EMBEDDING, None),
        (RERANKER, None),
    ]
    assert hub.downloads[0][1][-1] == "model.onnx"
    marker = json.loads((tmp_path / EMBEDDING / MODEL_MARKER).read_text())
    assert (marker["role"], marker["dimensions"], marker["revision"]) == (
        "embedding",
        32,
        "f" * 40,
    )
    assert not (tmp_path / EMBEDDING / ".cache").exists()
    assert sorted(p.name for p in (tmp_path / "exactdocs-test").iterdir()) == [
        "tiny-embedding",
        "tiny-reranker",
    ]  # no staging folder left behind
    assert LocalModels(models_dir=tmp_path).missing(EMBEDDING, ModelRole.EMBEDDING) is None


def test_pull_refuses_a_model_fastembed_does_not_have(tmp_path: Path) -> None:
    [outcome] = pull(["acme/not-a-model"], tmp_path, download=FakeHub(tmp_path))

    assert not outcome.ok
    assert "fastembed supports no" in outcome.message


def test_a_download_without_a_tokenizer_is_not_stored(models_dir: Path, tmp_path: Path) -> None:
    [outcome] = pull([EMBEDDING], tmp_path, download=FakeHub(models_dir, drop="tokenizer.json"))

    assert not outcome.ok
    assert "has no tokenizer.json" in outcome.message
    assert not (tmp_path / EMBEDDING).exists()
    assert LocalModels(models_dir=tmp_path).missing(EMBEDDING, ModelRole.EMBEDDING) is not None


def test_the_pull_command_reports_each_model_and_fails_when_one_failed(
    models_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EXACTDOCS_MODELS_DIR", str(tmp_path))
    hub = FakeHub(models_dir)
    monkeypatch.setattr(cli, "pull_models", lambda models, into: pull(models, into, download=hub))

    with pytest.raises(SystemExit) as exited:
        cli.app(
            ["models", "pull", EMBEDDING, "acme/not-a-model"],
            exit_on_error=False,
            result_action="return_value",
        )

    assert exited.value.code == 1
    out = capsys.readouterr().out
    assert f"{EMBEDDING}: ok  pulled into {tmp_path / EMBEDDING}" in out
    assert "acme/not-a-model: error  fastembed supports no" in out


def test_the_pull_command_pulls_the_two_defaults_when_none_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXACTDOCS_MODELS_DIR", str(tmp_path))
    asked: list[Sequence[str]] = []
    monkeypatch.setattr(cli, "pull_models", lambda models, _into: asked.append(models) or [])

    cli.app(["models", "pull"], exit_on_error=False, result_action="return_value")

    assert asked == [("BAAI/bge-small-en-v1.5", "Xenova/ms-marco-MiniLM-L-6-v2")]


# ---------------------------------------------------------------- review round 1 (#278)

PINNED = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
BGE = "BAAI/bge-small-en-v1.5"


def _marker(models_dir: Path, revision: str | None) -> None:
    folder = models_dir / BGE
    folder.mkdir(parents=True, exist_ok=True)
    marker = {"model": BGE, "role": "embedding", "dimensions": 384, "revision": revision}
    (folder / MODEL_MARKER).write_text(json.dumps(marker))


def test_a_default_model_pulled_at_another_revision_is_refused(tmp_path: Path) -> None:
    _marker(tmp_path, "0" * 40)
    reason = LocalModels(models_dir=tmp_path).missing(BGE, ModelRole.EMBEDDING)

    assert reason is not None
    assert f"pulled at revision {'0' * 40}, not the pinned {PINNED}" in reason
    assert f"`exactdocs models pull {BGE}` again" in reason
    _marker(tmp_path, PINNED)
    assert LocalModels(models_dir=tmp_path).missing(BGE, ModelRole.EMBEDDING) is None


def test_pull_fetches_a_default_model_at_its_pinned_revision_and_again_on_a_mismatch(
    tmp_path: Path,
) -> None:
    _marker(tmp_path, None)  # pulled before revisions were recorded
    hub = FakeHub(tmp_path / "no-fixture")

    [first] = pull([BGE], tmp_path, download=hub)
    [second] = pull([BGE], tmp_path, download=hub)

    assert first.ok, first.message
    assert f"at {PINNED[:12]}" in first.message
    assert second.message.startswith("already in")
    assert [(r, revision) for r, _, revision in hub.downloads] == [
        ("Qdrant/bge-small-en-v1.5-onnx-Q", PINNED)
    ]
    marker = json.loads((tmp_path / BGE / MODEL_MARKER).read_text())
    assert marker["revision"] == PINNED


@pytest.mark.parametrize(("cores", "threads"), [(8, 4), (4, 2), (1, 1), (None, 1)])
def test_onnx_runtime_gets_half_the_cores(
    monkeypatch: pytest.MonkeyPatch, cores: int | None, threads: int
) -> None:
    monkeypatch.setattr(local_models.os, "cpu_count", lambda: cores)

    assert local_models.onnx_threads() == threads


async def test_close_shuts_the_pools_down_and_a_later_call_makes_new_ones(
    models_dir: Path,
) -> None:
    local = LocalModels(models_dir=models_dir)
    first = await local.embedder(OFFLINE, EMBEDDING)
    assert isinstance(first, LocalEmbedder)
    assert first.executor is not first.query_executor  # batches never hold a search's pool

    local.close()

    with pytest.raises(RuntimeError, match="after shutdown"):
        first.query_executor.submit(print)
    again = await local.embedder(OFFLINE, EMBEDDING)
    assert isinstance(again, LocalEmbedder)
    assert again.model is first.model  # the model stays loaded
    assert again.query_executor is not first.query_executor


def _configured(ai: dict) -> ConfiguredAi:
    return configured_ai(AiSettings.model_validate(ai))


@pytest.mark.parametrize(
    ("reranker", "timeout"),
    [
        ({"model": "local:Xenova/ms-marco-MiniLM-L-6-v2"}, None),
        ({"model": "local:Xenova/ms-marco-MiniLM-L-6-v2", "timeout": 1.5}, 1.5),
        ({}, None),
    ],
)
def test_the_rerank_timeout_setting_is_passed_through_unresolved(
    tmp_path: Path, reranker: dict, timeout: float | None
) -> None:
    # Which default an unset timeout gets is decided per search by the reranker's profile
    # (test_reranking.py); the container only passes the operator's value on (#284).
    ai = {"providers": {"local": {"kind": "local"}}, "reranker": reranker}

    limits = _rerank_limits(Settings(data_dir=tmp_path, ai=AiSettings.model_validate(ai)))

    assert limits.timeout == timeout


def test_a_local_role_without_a_local_profile_is_warned_about_at_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="exactdocs"):
        _warn_undeclared_local(_configured({"embedding": {"model": f"local:{BGE}"}}))
        _warn_undeclared_local(
            _configured(
                {"providers": {"local": {"kind": "local"}}, "embedding": {"model": f"local:{BGE}"}}
            )
        )

    [warning] = [r.getMessage() for r in caplog.records]
    assert "AI role embedding names profile 'local', which is not configured" in warning
    assert "EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local" in warning


# ---------------------------------------------------------------- budgets (#268) with local models


async def _embedded_and_searched(
    docs_repo: DocsRepo,
    data_dir: Path,
    models_dir: Path,
    budgets: dict,
    spent: Sequence[SpendEntry] = (),
) -> tuple[tuple[int, float], SearchDocsResult, tuple[int, float]]:
    ai = AiSettings.model_validate(
        {
            "mode": "hybrid",
            "providers": {"local": {"kind": "local"}},
            "embedding": {"model": f"local:{EMBEDDING}"},
            "reranker": {"model": f"local:{RERANKER}"},
            "budgets": budgets,
        }
    )
    container = Container.build(Settings(data_dir=data_dir, models_dir=models_dir, ai=ai))
    async with container.running(jobs=False):
        await SqliteSpendLedger(engine=container.engine).add(spent)  # earlier, paid calls
        await import_fixture(container, docs_repo)
        try:
            await embed_fixture(container)
        finally:
            before = await instance_spend(container.engine)
        answer = await container.retrieval.search_docs(
            SearchDocsQuery(library=LIBRARY, ref="v1.4.0", query="how do I retry failed calls")
        )
        return before, answer, await instance_spend(container.engine)


async def test_a_local_model_costs_nothing_so_a_usd_budget_starts_and_never_stops_it(
    docs_repo: DocsRepo, tmp_path: Path, models_dir: Path
) -> None:
    budgets = {"daily_usd": 0.01, "daily_embedding_usd": 0.01}

    embedded, answer, after = await _embedded_and_searched(
        docs_repo, tmp_path / "data", models_dir, budgets
    )

    tokens, usd = embedded
    assert tokens > 0  # the tokens count
    assert usd == 0  # the price is 0, so the USD budget is never reached
    assert (answer.retrieval_mode, answer.fallback_reason, answer.reranked) == (
        "hybrid",
        None,
        True,
    )
    assert after[0] > tokens  # the query embedding is recorded too
    assert after[1] == 0


async def test_a_used_up_token_budget_never_stops_local_models(
    docs_repo: DocsRepo, tmp_path: Path, models_dir: Path
) -> None:
    # #284: local tokens are recorded but count toward no token budget, and a budget that paid
    # calls used up stops neither the local embedding job nor a local query embedding or rerank.
    budgets = {"daily_tokens": 1000, "daily_embedding_tokens": 1000}
    today = SpendWindow.DAY.start(datetime.now(UTC))
    spent = [
        SpendEntry(
            scope_kind=kind,
            scope_id="",
            window=SpendWindow.DAY,
            window_start=today,
            input_tokens=1000,
            requests=1,
        )
        for kind in ("instance", "embedding")
    ]

    embedded, answer, after = await _embedded_and_searched(
        docs_repo, tmp_path / "data", models_dir, budgets, spent
    )

    assert embedded[0] > 0  # the job's tokens are recorded (the paid ones are daily rows only)
    assert (answer.retrieval_mode, answer.fallback_reason, answer.reranked) == (
        "hybrid",
        None,
        True,
    )
    assert after[0] > embedded[0]  # and the query embedding's and the rerank's
