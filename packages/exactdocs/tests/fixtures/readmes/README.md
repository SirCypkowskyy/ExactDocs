# README fixtures: provenance

Shortened excerpts of real projects' README files, kept for the README-title tests
(`tests/ingestion/test_readme.py`, `features/library_readme.feature`): a logo or badge block
before the first heading must not become the library's name. They are test data, not
documentation: the exactdocs sdist carries them with the tests (and this file with them), the
wheel and the image do not.

Each file keeps the original's opening markup (logo, badges, links) and its first lines, cut down
to a few sections. Some text was rewritten or added to exercise a parsing case (in
`pydantic-ai.md`, for instance, the blockquote "A blockquote is never the description."). They
are not the current README of either project.

| File | Source | Licence | Copyright |
|---|---|---|---|
| `fastapi.md` | `README.md` of [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT | Copyright (c) 2018 Sebastián Ramírez |
| `pydantic-ai.md` | `README.md` of [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | MIT | Copyright (c) Pydantic Services Inc. 2024 to present |

The logos and badges are linked, not copied: no image is stored here. The names FastAPI and
Pydantic AI belong to their owners.

Both excerpts are used under the MIT License, whose text follows:

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
