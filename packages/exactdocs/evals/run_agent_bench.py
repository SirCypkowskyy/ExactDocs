"""The agent benchmark: ``just agent-bench run|sample|agreement`` (docs/evals/agent-bench.md).

As in ``run_retrieval_eval.py``, the test-support directory (the importer wiring) is put on the
path before the CLI is imported.
"""

import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "fixtures"))

if __name__ == "__main__":
    sys.exit(import_module("agent_bench.cli").main())
