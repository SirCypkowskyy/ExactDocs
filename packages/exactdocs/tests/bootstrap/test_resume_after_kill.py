"""A killed process: the import resumes on the next start where it stopped, without duplicates.

The import runs in a child process (``fixtures/import_child.py``) that kills itself with SIGKILL
before chunking file 121 of 200: no clean-up, no cancellation, exactly what a crash or an OOM
kill leaves behind. Then ExactDocs starts again on the same data directory.
"""

import json
import signal
from pathlib import Path

import reprocess_child
from import_child import big_repository, page, run

FILES = 200


async def test_an_import_killed_after_120_files_finishes_from_file_121_without_duplicates(
    tmp_path: Path,
) -> None:
    url, commit = big_repository(tmp_path / "repo", FILES)
    data, log = tmp_path / "data", tmp_path / "chunked.log"

    code, _, err = await run(str(data), url, commit, str(log), "120")
    assert code == -signal.SIGKILL, err
    assert log.read_text().splitlines() == [page(n) for n in range(1, 121)]

    log.unlink()
    code, out, err = await run(str(data), url, "-", str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == [page(n) for n in range(121, FILES + 1)]
    job = json.loads(out)
    assert (job["state"], job["done"], job["total"]) == ("succeeded", FILES, FILES)
    assert job["articles"] == [page(n) for n in range(1, FILES + 1)]  # each exactly once


async def test_a_reprocess_killed_in_its_second_version_resumes_without_redoing_the_first(
    tmp_path: Path,
) -> None:
    url = reprocess_child.tagged_repository(tmp_path / "repo", 30)
    data, log = tmp_path / "data", tmp_path / "stored.log"

    # Stores 1 and 2 are the imports of v1 and v2, 3 the re-import of v1; it dies at the 4th.
    code, _, err = await reprocess_child.run(str(data), url, str(log), "4")
    assert code == -signal.SIGKILL, err
    assert log.read_text().splitlines() == ["v1", "v2", "v1"]

    log.unlink()
    code, out, err = await reprocess_child.run(str(data), url, str(log))
    assert code == 0, err

    assert log.read_text().splitlines() == ["v2"]  # v1's re-import is not run again
    job = json.loads(out)
    assert job["state"] == "succeeded", job
    expected = [page(n) for n in range(10, 31)]  # docs/page-00*.md left out
    assert job["versions"] == {"v1": expected, "v2": expected}
