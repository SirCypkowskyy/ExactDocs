# Re-asked questions

!!! abstract "TL;DR"

    - The agentic answer cache is off by default.
    - It serves only near-verbatim re-asks of the same version, tags, model and limits.
    - The rules lean towards a miss: a wrong match serves a wrong answer.
    - With `scope = "library"` callers share answers; use `scope = "caller"` where they must not.

Teams ask the same thing more than once. With the agentic answer cache on, an agentic answer is
kept, and a later question that asks the same thing again is answered from it at once: with
`cache_hit: true`, the same results, justifications and explored paths, and no LLM call, budget or
rate limit (counted in `exactdocs.ai.cache_hits`).

```toml
[ai.agentic_cache]
enabled = true       # off by default: while off, stored answers are deleted
# threshold = 0.8    # 0 to 1; unset: 0.8 with an embedding model, 0.9 with words alone
scope = "library"    # or "caller": each caller is answered from their own questions only
ttl = "P7D"          # seconds or an ISO 8601 duration
```

The cache is opt-in, with an embedding model too. It trades exactness for cost and serves only
near-verbatim re-asks.

## When an answer is reused

Only for the same version as it is now (a re-sync to a new commit, or
a new manifest, never reuses it), the same tag filter, the same `llm` model and the same
`[ai.agentic]` limits. Each of its chunks is looked up again in the version, under the call's tags,
before it is returned, and an answer none of whose chunks are left runs the agent instead.

## What counts as the same question

The same content words in the same order. Filler such as
"how", "do", "I", "I want" or "behaviour" is dropped, and only plurals fold ("retries"/"retry",
"rows"/"row"), so "how do I configure retries", "how to configure retry behaviour" and "I want to
configure retries" are one question. The rules lean towards a miss, because a wrong fold serves a
wrong answer and a missing one only costs an LLM call:

- Nothing else folds: "connecting" is not "connect", "meaning" is not "mean", "migration" is not
  "migrate", and "format" is never "form".
- Question words ("when" is not "why"), prepositions and conjunctions ("build for arm" is not
  "build on arm") stay.
- Order is part of the question, so every swap misses: "replace requests with httpx" is not
  "replace httpx with requests", and "from v1 to v2" is not "to v1 from v2". An order-flipped
  re-ask ("retry configuration" for "configure retries") is therefore a miss too, which is accepted.
- Symbols are terms in their places: "latency > threshold" is not "latency < threshold", `c++` is
  not `c`, and `≥`, `≤`, `≠`, `≈` and `→` read as `>=`, `<=`, `!=`, `~=` and `->`. Only sentence
  punctuation is dropped.
- Single letters are terms too, but "a" and "I" only as names, next to a symbol or a direction word
  ("move it to a from b").
- Numbers and versions must match exactly, with their sign, a comparison or range operator right
  before them and a `+` right after: `-1` is not `1`, `>= 3.8` is not `< 3.8`, `~1.2` is not
  `^1.2`, and `3.8+` is not `3.8`. So must words with digits (`python3`, `oauth2`, `E42`) and
  negations ("not", "never", "without", "can't", "dont"...).
- A question with a word the other lacks never hits, and neither does a paraphrase in other words.
  Neither words nor embeddings tell "enable" from "disable" or "client" from "server": the default
  local model scores those pairs 0.85 to 0.96, as high as real paraphrases.

With an embedding model, the cosine of the two questions' embeddings must also clear the threshold,
as a confirmation. It never makes two different questions match. The threshold is 0.8 with an
embedding model and 0.9 with words alone by default.

Saving a library's retrieval settings, or removing the library, forgets its answers. The nightly
upkeep deletes answers past `ttl`, answers of an `llm` model that is no longer configured, answers
compared with another embedding model than the configured one, and every answer while the cache is
off.

!!! warning "Shared answers"
    With `scope = "library"` (the default) every caller of a library's version shares the cache.
    One caller's cached answer, including the model's justifications, which may paraphrase their
    question, can be served to another caller of the same library and version. Use
    `scope = "caller"` where callers must not see the gist of each other's questions.

## What the cache stores

The cache (`retrieval_agentic_answers`) never stores the question's text.
It keeps an HMAC of the normalized question and of each of its terms, keyed from the instance's
secret key, and, with an embedding model, the question's embedding. An embedding can be partly
inverted into the words it came from, so treat the table as holding what the question meant. It
also keeps the answer as returned (chunk IDs, justifications and explored paths), which is model
output and may quote words of the question. The question's embedding is a query embedding like a
hybrid search's: it is sent to the embedding model and counted to the same budgets.
