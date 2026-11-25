"""The version-pinned coding tasks: ``just coding-tasks list|prepare|check|run`` (docs/evals.md).

As in ``run_agent_bench.py``, the test-support directory (the importer wiring the ``exactdocs``
arm needs) is put on the path before the CLI is imported.
"""

import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "fixtures"))

if __name__ == "__main__":
    sys.exit(import_module("coding_tasks.cli").main())
