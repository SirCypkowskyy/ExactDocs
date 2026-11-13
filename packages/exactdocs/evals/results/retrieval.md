# Retrieval benchmark

The golden set's 321 cases (`sha256:39f6f9d5e909d128`) on starlette, pydantic, tanstack-query, zod, electron, every pinned version, per configuration and chunking. ExactDocs `fe156aa8aed0ebd86bcb45e930be9769e4056535`, Darwin arm64. Recall, MRR and nDCG over answerable cases; unanswerable cases scored on returning nothing of another version (clean) and on coming back empty (no answer). Definitions: docs/evals.md#the-retrieval-benchmark.

## Recommended defaults

| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `h3-max-4000` | $0.0000 | best none configuration: `bm25` at `h3-max-4000`: recall@5 81.7%, nDCG@10 0.705, MRR 0.651, wrong-version rate 0, p95 57 ms, $0.0000 per 1000 questions |
| local | `bm25` | `h3-max-4000` | $0.0000 | best local configuration: `hybrid:bge-small-en-v1.5` at `default`: recall@5 84.6%, nDCG@10 0.738, MRR 0.675, wrong-version rate 0, p95 127 ms, $0.0000 per 1000 questions; +3.0 points of recall@5 over `bm25`, under the 5-point margin: the cheaper `bm25` at `h3-max-4000` stays the default |
| hosted | not measured yet: needs a real-providers run | - | - | - |

## Every configuration

| configuration | chunking | budget | status | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | unanswerable clean / no answer | answerable empty | p50 ms | p95 ms | tokens/q | USD/1000q | index s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `bm25` | `default` | none | ran | 49.8% | 79.8% | 86.9% | 0.626 | 0.684 | 0 | 100.0% / 0.0% | 0.0% | 71.9 | 90.9 | 0 | 0.0000 | - |
| `bm25+ce` | `default` | local | ran | 57.7% | 84.6% | 90.3% | 0.692 | 0.732 | 0 | 100.0% / 0.0% | 0.0% | 1356.6 | 1590.5 | 9158 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `default` | local | ran | 54.7% | 84.6% | 91.4% | 0.675 | 0.738 | 0 | 100.0% / 0.0% | 0.0% | 96.2 | 127.0 | 22 | 0.0000 | 1026 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | local | ran | 57.3% | 83.5% | 90.3% | 0.689 | 0.730 | 0 | 100.0% / 0.0% | 0.0% | 1389.7 | 1655.1 | 8566 | 0.0000 | 1026 |
| `hybrid:snowflake-arctic-embed-s` | `default` | local | ran | 40.1% | 75.3% | 84.6% | 0.547 | 0.611 | 0 | 100.0% / 0.0% | 0.0% | 95.2 | 123.4 | 22 | 0.0000 | 962 |
| `bm25` | `h2` | none | ran | 51.7% | 76.0% | 81.7% | 0.626 | 0.665 | 0 | 100.0% / 0.0% | 0.0% | 20.8 | 25.9 | 0 | 0.0000 | - |
| `bm25+ce` | `h2` | local | ran | 48.3% | 72.7% | 79.8% | 0.590 | 0.645 | 0 | 100.0% / 0.0% | 0.0% | 1332.1 | 1476.9 | 21844 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h2` | local | ran | 51.7% | 73.4% | 80.5% | 0.612 | 0.670 | 0 | 100.0% / 0.0% | 0.0% | 48.9 | 65.3 | 22 | 0.0000 | 462 |
| `bm25` | `h3-max-4000` | none | ran | 52.1% | 81.7% | 89.1% | 0.651 | 0.705 | 0 | 100.0% / 0.0% | 0.0% | 47.6 | 56.7 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `h3-max-4000` | local | ran | 56.5% | 84.3% | 90.3% | 0.687 | 0.742 | 0 | 100.0% / 0.0% | 0.0% | 69.4 | 88.9 | 22 | 0.0000 | 810 |
| `bm25` | `merge-400` | none | ran | 49.1% | 74.2% | 80.5% | 0.602 | 0.645 | 0 | 100.0% / 0.0% | 0.0% | 33.6 | 39.8 | 0 | 0.0000 | - |
| `hybrid:bge-small-en-v1.5` | `merge-400` | local | ran | 52.1% | 78.3% | 83.5% | 0.638 | 0.687 | 0 | 100.0% / 0.0% | 0.0% | 60.7 | 75.8 | 22 | 0.0000 | 673 |

## By question kind (recall@5 / section recall@5 / nDCG@10)

| configuration | chunking | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `bm25` | `default` | 82.7% / 79.2% / 0.674 | 66.0% / 50.2% / 0.561 | 81.1% / 76.4% / 0.698 | 80.8% / 79.8% / 0.698 | clean 100.0%, no answer 0.0% | 87.7% / 84.2% / 0.780 |
| `bm25+ce` | `default` | 90.4% / 87.8% / 0.790 | 73.6% / 57.7% / 0.597 | 84.9% / 83.0% / 0.757 | 88.5% / 88.5% / 0.757 | clean 100.0%, no answer 0.0% | 86.0% / 83.3% / 0.760 |
| `hybrid:bge-small-en-v1.5` | `default` | 84.6% / 82.0% / 0.730 | 77.4% / 64.8% / 0.643 | 84.9% / 82.1% / 0.756 | 86.5% / 86.5% / 0.764 | clean 100.0%, no answer 0.0% | 89.5% / 86.8% / 0.793 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 88.5% / 86.9% / 0.779 | 73.6% / 56.1% / 0.603 | 83.0% / 82.1% / 0.766 | 88.5% / 88.5% / 0.744 | clean 100.0%, no answer 0.0% | 84.2% / 81.6% / 0.756 |
| `hybrid:snowflake-arctic-embed-s` | `default` | 82.7% / 78.8% / 0.659 | 64.1% / 45.3% / 0.469 | 75.5% / 71.7% / 0.591 | 80.8% / 81.7% / 0.682 | clean 100.0%, no answer 0.0% | 73.7% / 74.6% / 0.653 |
| `bm25` | `h2` | 78.8% / 72.8% / 0.692 | 69.8% / 56.3% / 0.592 | 83.0% / 76.4% / 0.717 | 82.7% / 82.7% / 0.752 | clean 100.0%, no answer 0.0% | 66.7% / 64.9% / 0.580 |
| `bm25+ce` | `h2` | 76.9% / 73.7% / 0.688 | 64.1% / 57.2% / 0.580 | 83.0% / 78.3% / 0.703 | 80.8% / 80.8% / 0.720 | clean 100.0%, no answer 0.0% | 59.7% / 58.8% / 0.542 |
| `hybrid:bge-small-en-v1.5` | `h2` | 80.8% / 75.6% / 0.691 | 66.0% / 64.1% / 0.634 | 83.0% / 78.3% / 0.760 | 80.8% / 80.8% / 0.744 | clean 100.0%, no answer 0.0% | 57.9% / 55.3% / 0.535 |
| `bm25` | `h3-max-4000` | 82.7% / 78.2% / 0.688 | 71.7% / 53.9% / 0.585 | 83.0% / 77.4% / 0.740 | 82.7% / 82.7% / 0.745 | clean 100.0%, no answer 0.0% | 87.7% / 84.2% / 0.762 |
| `hybrid:bge-small-en-v1.5` | `h3-max-4000` | 84.6% / 81.7% / 0.700 | 75.5% / 65.1% / 0.662 | 84.9% / 81.1% / 0.744 | 86.5% / 87.5% / 0.806 | clean 100.0%, no answer 0.0% | 89.5% / 86.8% / 0.793 |
| `bm25` | `merge-400` | 76.9% / 73.4% / 0.677 | 60.4% / 48.4% / 0.496 | 77.4% / 71.7% / 0.695 | 69.2% / 68.3% / 0.614 | clean 100.0%, no answer 0.0% | 86.0% / 83.3% / 0.737 |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 80.8% / 78.2% / 0.707 | 69.8% / 59.8% / 0.588 | 81.1% / 76.4% / 0.720 | 76.9% / 77.9% / 0.670 | clean 100.0%, no answer 0.0% | 82.5% / 79.8% / 0.746 |

## By project (recall@5 / section recall@5 / nDCG@10)

| configuration | chunking | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `bm25` | `default` | 77.4% / 70.8% / 0.660 | 81.8% / 73.2% / 0.668 | 85.2% / 80.6% / 0.734 | 75.0% / 68.6% / 0.601 | 79.2% / 77.0% / 0.753 |
| `bm25+ce` | `default` | 81.1% / 76.1% / 0.702 | 83.6% / 79.5% / 0.720 | 90.7% / 84.0% / 0.802 | 78.8% / 75.3% / 0.658 | 88.7% / 85.2% / 0.777 |
| `hybrid:bge-small-en-v1.5` | `default` | 84.9% / 77.4% / 0.736 | 83.6% / 81.2% / 0.713 | 87.0% / 82.7% / 0.779 | 78.8% / 75.3% / 0.646 | 88.7% / 85.9% / 0.813 |
| `hybrid:bge-small-en-v1.5+ce` | `default` | 81.1% / 77.4% / 0.705 | 80.0% / 75.9% / 0.719 | 92.6% / 84.0% / 0.802 | 76.9% / 73.4% / 0.651 | 86.8% / 84.3% / 0.769 |
| `hybrid:snowflake-arctic-embed-s` | `default` | 69.8% / 64.8% / 0.580 | 83.6% / 78.2% / 0.664 | 70.4% / 65.7% / 0.586 | 76.9% / 70.5% / 0.570 | 75.5% / 72.6% / 0.653 |
| `bm25` | `h2` | 77.4% / 70.4% / 0.639 | 72.7% / 65.5% / 0.619 | 85.2% / 81.2% / 0.792 | 61.5% / 58.0% / 0.549 | 83.0% / 77.0% / 0.722 |
| `bm25+ce` | `h2` | 75.5% / 68.9% / 0.634 | 72.7% / 71.8% / 0.651 | 81.5% / 78.4% / 0.720 | 55.8% / 56.1% / 0.515 | 77.4% / 72.0% / 0.700 |
| `hybrid:bge-small-en-v1.5` | `h2` | 71.7% / 65.7% / 0.629 | 72.7% / 68.5% / 0.663 | 79.6% / 78.1% / 0.752 | 63.5% / 63.8% / 0.573 | 79.2% / 76.4% / 0.730 |
| `bm25` | `h3-max-4000` | 79.2% / 70.8% / 0.692 | 81.8% / 74.1% / 0.674 | 85.2% / 81.5% / 0.761 | 75.0% / 67.6% / 0.620 | 86.8% / 82.7% / 0.775 |
| `hybrid:bge-small-en-v1.5` | `h3-max-4000` | 84.9% / 79.2% / 0.763 | 83.6% / 81.2% / 0.713 | 85.2% / 80.9% / 0.763 | 78.8% / 75.3% / 0.655 | 88.7% / 85.9% / 0.813 |
| `bm25` | `merge-400` | 71.7% / 66.0% / 0.618 | 80.0% / 73.6% / 0.645 | 74.1% / 72.8% / 0.672 | 71.2% / 65.7% / 0.613 | 73.6% / 67.6% / 0.676 |
| `hybrid:bge-small-en-v1.5` | `merge-400` | 77.4% / 71.1% / 0.680 | 81.8% / 79.4% / 0.689 | 77.8% / 75.6% / 0.698 | 75.0% / 71.5% / 0.632 | 79.2% / 74.5% / 0.734 |

## Not run

- `bm25+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:bge-small-en-v1.5+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:snowflake-arctic-embed-s+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:bge-base-en-v1.5+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted+ce`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hybrid:hosted+judge`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `hyde:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))
- `agentic:hosted`: skipped (needs a real-providers run (--allow-providers, eval-providers.yml))

## Models

- reranker: `local:Xenova/ms-marco-MiniLM-L-6-v2` @ `a09144355ade`
- embedding: `local:BAAI/bge-small-en-v1.5` @ `aa8f8b060edb`
- embedding: `local:snowflake/snowflake-arctic-embed-s` @ `e596f5074675`
