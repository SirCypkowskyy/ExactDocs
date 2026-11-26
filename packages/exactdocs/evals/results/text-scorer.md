# Text scorer calibration

ExactDocs' BM25 results for the golden set's 321 cases (`sha256:100484c7ccdb1b89`) on starlette, pydantic, tanstack-query, zod, electron, scored by chunk ID and from their text alone: 5-word shingles, threshold 0.8, facts at 0.75 of their words. A decision is where an expected section is in the top 10 (its rank), or that it is not; the criterion is 98.0% agreement at `default`. ExactDocs `08349c19d4fec0630e61b7f4394797373409af38`. Definitions: docs/evals/text-scoring.md.

## Agreement with chunk-ID scoring

| chunking | decisions | same rank | hit / miss | rendered as plain text | wrong version (cases) | criterion |
|---|---|---|---|---|---|---|
| `default` | 404 | 99.8% | 100.0% | 99.8% | 100.0% | met |
| `h6` | 404 | 99.8% | 100.0% | 99.8% | 100.0% | - |
| `h2` | 404 | 99.8% | 100.0% | 99.5% | 100.0% | - |
| `merge-400` | 404 | 99.5% | 99.8% | 99.5% | 100.0% | - |

## Threshold sweep (same rank; as returned / rendered as plain text)

| threshold | `default` | `h6` | `h2` | `merge-400` |
|---|---|---|---|---|
| 0.5 | 97.5% / 97.5% | 96.8% / 96.8% | 98.0% / 98.0% | 97.5% / 97.5% |
| 0.6 | 97.8% / 97.8% | 97.0% / 97.0% | 98.5% / 98.5% | 98.3% / 98.3% |
| 0.7 | 98.8% / 98.8% | 98.5% / 98.5% | 99.0% / 99.0% | 98.5% / 98.5% |
| 0.8 (chosen) | 99.8% / 99.8% | 99.8% / 99.8% | 99.8% / 99.5% | 99.5% / 99.5% |
| 0.9 | 100.0% / 99.5% | 100.0% / 99.8% | 100.0% / 98.8% | 99.8% / 99.3% |
| 1 | 100.0% / 90.3% | 100.0% / 90.8% | 100.0% / 88.1% | 99.8% / 88.6% |

## Both scorings side by side

| chunking | scored by | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer |
|---|---|---|---|---|---|---|---|---|---|
| `default` | chunk ID | 58.8% | 87.6% | 93.6% | 76.6% | 0.711 | 0.714 | 0.0% | 0.0% |
| `default` | text | 58.8% | 87.6% | 93.6% | 76.6% | 0.711 | 0.714 | 0.0% | 0.0% |
| `h6` | chunk ID | 56.9% | 85.8% | 92.1% | 75.3% | 0.689 | 0.692 | 0.0% | 0.0% |
| `h6` | text | 56.9% | 85.8% | 92.1% | 75.3% | 0.689 | 0.692 | 0.0% | 0.0% |
| `h2` | chunk ID | 61.8% | 89.1% | 94.0% | 77.4% | 0.737 | 0.724 | 0.0% | 0.0% |
| `h2` | text | 61.8% | 89.1% | 94.0% | 77.4% | 0.737 | 0.724 | 0.0% | 0.0% |
| `merge-400` | chunk ID | 59.6% | 87.6% | 93.3% | 77.3% | 0.715 | 0.720 | 0.0% | 0.0% |
| `merge-400` | text | 59.6% | 87.6% | 93.3% | 77.3% | 0.715 | 0.719 | 0.0% | 0.0% |

## What only the text tells

| chunking | results / q | version-neutral | unmatched | context tokens / q | p95 | tokens to first hit | facts found | facts in the expected sections | facts in another question's results |
|---|---|---|---|---|---|---|---|---|---|
| `default` | 10.0 | 72.2% | 0.0% | 3464 | 5945 | 656 | 87.0% | 80.6% | 24.6% |
| `h6` | 10.0 | 72.2% | 0.0% | 2874 | 5345 | 583 | 84.2% | 80.6% | 21.4% |
| `h2` | 10.0 | 75.5% | 0.0% | 7065 | 11346 | 1366 | 92.8% | 80.6% | 41.8% |
| `merge-400` | 10.0 | 73.3% | 0.0% | 3535 | 5957 | 656 | 87.1% | 80.6% | 26.2% |

## Disagreements

- `default`: 1
  - tanstack-query v5.90.3: How do I stream useSuspenseQuery results from the server in Next.js without prefetching, and what is the cost?: v5.90.3 docs/framework/react/guides/suspense.md [Suspense on the Server with streaming]: chunk ID 7, text 1; the chunk at rank 1 (v5.90.3 docs/framework/react/guides/advanced-ssr.md [Experimental streaming without prefetching in Next.js]) holds the section's text, but is another article or version
- `h6`: 1
  - tanstack-query v5.90.3: How do I stream useSuspenseQuery results from the server in Next.js without prefetching, and what is the cost?: v5.90.3 docs/framework/react/guides/suspense.md [Suspense on the Server with streaming]: chunk ID 7, text 1; the chunk at rank 1 (v5.90.3 docs/framework/react/guides/advanced-ssr.md [Experimental streaming without prefetching in Next.js]) holds the section's text, but is another article or version
- `h2`: 1
  - tanstack-query v5.90.3: How do I stream useSuspenseQuery results from the server in Next.js without prefetching, and what is the cost?: v5.90.3 docs/framework/react/guides/suspense.md [Suspense on the Server with streaming]: chunk ID 7, text 1; the chunk at rank 1 (v5.90.3 docs/framework/react/guides/advanced-ssr.md [Experimental streaming without prefetching in Next.js]) holds the section's text, but is another article or version
- `merge-400`: 2
  - electron v30.0.0: What do I need on the signing side before autoUpdater can update my Mac app?: v30.0.0 docs/tutorial/code-signing.md [Signing & notarizing macOS builds]: chunk ID 10, text -; the chunk at rank 10 (v30.0.0 docs/tutorial/code-signing.md [Signing & notarizing macOS builds > Signing Mac App Store applications]) holds less than the threshold of the section's text
  - tanstack-query v5.90.3: How do I stream useSuspenseQuery results from the server in Next.js without prefetching, and what is the cost?: v5.90.3 docs/framework/react/guides/suspense.md [Suspense on the Server with streaming]: chunk ID 7, text 1; the chunk at rank 1 (v5.90.3 docs/framework/react/guides/advanced-ssr.md [Experimental streaming without prefetching in Next.js]) holds the section's text, but is another article or version
