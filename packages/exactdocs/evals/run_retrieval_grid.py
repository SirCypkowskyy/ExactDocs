"""The retrieval grid: ``just retrieval-grid`` (docs/evals/retrieval-grid.md).

As in ``run_retrieval_bench.py``, the test-support directory (the importer wiring) is put on the
path before the CLI is imported.
"""

import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "fixtures"))

if __name__ == "__main__":
    sys.exit(import_module("retrieval_eval.grid_cli").main())
