"""Run the retrieval eval suite: ``just eval [--help]`` (docs/evals/suite.md).

The fixture builder is test support, not part of the package: its directory is put on the path
here, then the suite is imported (``import_module`` keeps the path change before the import).
"""

import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "fixtures"))

if __name__ == "__main__":
    sys.exit(import_module("retrieval_eval.cli").main())
