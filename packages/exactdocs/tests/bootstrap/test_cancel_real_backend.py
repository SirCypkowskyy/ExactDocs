"""A cancelled import on the real job backend (#432): DBOS on SQLite and on PostgreSQL.

The import runs in a child process (``fixtures/import_child.py``) that cancels its own job, as
``POST /jobs/{id}/cancel`` does, while it cuts a file of the first batch. The job stops at the
step boundary after that batch, publishes nothing, and is still cancelled when ExactDocs starts
again on the same database.
"""

import json
from pathlib import Path

import pytest

from databases import SQL_BACKENDS
from import_child import BATCH, big_repository, page, run

FILES = 200
CANCEL_AT = 5  # a file of the first batch


@pytest.fixture(params=SQL_BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    return request.param


@pytest.mark.usefixtures("backend")
async def test_an_import_cancelled_mid_run_stops_after_its_batch_and_stays_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    data, log = tmp_path / "data", tmp_path / "chunked.log"
    monkeypatch.setenv("IMPORT_CHILD_CANCEL_AT", str(CANCEL_AT))

    code, out, err = await run(str(data), url, commit, str(log))

    assert code == 0, err
    assert log.read_text().splitlines() == [page(n) for n in range(1, BATCH + 1)]  # one batch
    job = json.loads(out)
    assert (job["state"], job["cancelled_by"], job["done"]) == ("cancelled", "alice", BATCH)
    assert job["articles"] is None  # nothing was published: the version stays absent

    monkeypatch.delenv("IMPORT_CHILD_CANCEL_AT")
    log.unlink()
    code, out, err = await run(str(data), url, "-", str(log))  # ExactDocs starts again

    assert code == 0, err
    assert not log.exists()  # the cancelled job did not run again
    job = json.loads(out)
    assert (job["state"], job["cancelled_by"]) == ("cancelled", "alice")
    assert job["articles"] is None
