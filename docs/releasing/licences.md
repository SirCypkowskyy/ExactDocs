# Licences

!!! abstract "TL;DR"
    - What is published carries the licences of what it holds (#533).
    - Wheels and sdists carry the repository's `LICENSE`; the web UI carries
      `THIRD_PARTY_NOTICES.txt`; `check_artifacts.py wheel` fails a wheel without either.
    - In the images, each Python distribution carries its licence, and the `-local` models' licences
      are in `/opt/exactdocs/models/NOTICE`.

| What | Carries | Checked by |
|---|---|---|
| wheels and sdists of `exactdocs` and `exactdocs-kernel` | the repository's `LICENSE` | `tests/ci/test_licenses.py`, the release's *Build Python distributions* job |
| the web UI | `THIRD_PARTY_NOTICES.txt` | `check_artifacts.py wheel` |
| the images | each Python distribution's licence; the `-local` models' `NOTICE` | |
| test data from other projects | its source and licence, beside it | |

## Wheels and sdists

- `license-files` in each `pyproject.toml` names the `LICENSE`.
- PEP 639 allows no path outside the package, so each package holds a copy, which
  `tests/ci/test_licenses.py` keeps equal to the root one.

## The web UI

`THIRD_PARTY_NOTICES.txt` is written by `vite build` (`web/scripts/third-party-notices.ts`,
[web/README.md](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/web/README.md)). It holds:

- the licences of the npm packages in the bundle;
- the licences of its fonts (SIL Open Font License 1.1);
- the terms of the source adapted into it.

It ships in `exactdocs/_web/` in the wheel and in every image.

- `check_artifacts.py wheel` fails a wheel without it or without the `LICENSE`.
- The release's *Build Python distributions* job checks the `LICENSE` in every wheel and sdist.

## The images

- The images' Python distributions each carry their licence in their `.dist-info`.
- The `-local` default models' licences are in `/opt/exactdocs/models/NOTICE` (see
  [Model licenses](images.md#rules-per-variant)).

## Test data

Test data from other projects names its source and licence beside it
(`packages/exactdocs/tests/fixtures/readmes/README.md`); the sdist carries both.
