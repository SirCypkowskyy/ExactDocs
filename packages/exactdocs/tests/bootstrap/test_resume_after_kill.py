"""A killed process: the import resumes on the next start where it stopped, without duplicates.

The import runs in a child process (``fixtures/import_child.py``) that kills itself with SIGKILL
before chunking file 121 of 200: no clean-up, no cancellation, exactly what a crash or an OOM
kill leaves behind. Then ExactDocs starts again on the same data directory.
"""

import json
import signal
from pathlib import Path

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
