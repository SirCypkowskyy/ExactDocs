"""The retrieval eval suite: compares retrieval modes on the fixture docs repository.

A Pydantic Evals dataset (``dataset.yaml``) of questions pinned to one version each runs through
every retrieval mode this build can run; the suite reports recall@1/5/10, MRR, the wrong-version
rate, latency, tokens and USD per mode, and fails when a mode returns a result of another version
or the gating mode's recall@5 drops below the stored baseline. See docs/evals/suite.md.

Development and CI only: nothing here ships in the wheel, and ``pydantic-evals`` is a dev
dependency.
"""
