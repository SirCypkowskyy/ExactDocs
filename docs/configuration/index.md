# Configuration

!!! abstract "TL;DR"

    - ExactDocs runs with no configuration: SQLite in the data directory, a generated secret key, BM25 search.
    - Every setting is an `EXACTDOCS_<SETTING>` environment variable; nested ones use `__`.
    - The same settings can come from `.env` or from the TOML file `EXACTDOCS_CONFIG_FILE` names. The environment wins, field by field.
    - Secrets never go in the TOML file: the server refuses to start if they do.
    - To get started, read [Quick start](quick-start.md).

ExactDocs runs with no configuration at all: SQLite in the data directory, a generated secret key
and BM25 search. Everything in this section is optional.

## Which page do I need

| You want to | Read |
|---|---|
| Get a working instance with the few settings most people set | [Quick start](quick-start.md) |
| Set up a production instance step by step | [Detailed setup](detailed-setup.md) |
| Look up a setting of the data directory or the database | [Storage and database](storage.md) |
| Set allowed hosts, the public URL, cookies or the secret key | [Security and the secret key](security.md) |
| Let people sign in through OIDC, OAuth2, GitHub or Cloudflare Access | [Sign-in and access](sign-in/index.md) |
| Change the bind address, import limits or the CLI's server | [Server, imports and the CLI](server.md) |
| Choose a retrieval mode, model roles or an index backend | [Search and AI settings](ai.md) |
| Export traces and metrics, or count usage | [Observability and usage counts](observability.md) |
| Go through a proxy or trust a company CA | [Outbound connections](outbound.md) |
| Keep an index in Elasticsearch, Qdrant, Redis and the like | [External index backends](index-backends/index.md) |
| Run the database on libSQL, rotate the secret key, tune jobs | [Advanced](advanced.md) |

Models, rerankers, budgets and the agent are on [Search and AI models](../search/index.md); containers,
proxies, PostgreSQL and backups on [Deployment](../deployment/index.md).

## Where settings come from

Settings are environment variables named `EXACTDOCS_<SETTING>`. Nested settings use a double
underscore, as in `EXACTDOCS_AI__MODE` or `EXACTDOCS_AI__PROVIDERS__CORP__KIND`. They can also come
from a `.env` file in the working directory, or from a TOML file named by `EXACTDOCS_CONFIG_FILE`
(for example the `[ai]` tables on [Search and AI models](../search/index.md), or the `[auth]` tables on
[Sign-in and access](sign-in/index.md)).

When the same setting appears in several places, the environment wins over `.env`, and both win
over the TOML file, field by field.

!!! warning "No secrets in the TOML file"
    The TOML file may not hold API keys, client secrets or `secret_key`, and the server refuses to
    start if it does. Those come from the environment, or from the file that a model provider's
    `api_key_file` or a sign-in provider's `client_secret_file` names.
