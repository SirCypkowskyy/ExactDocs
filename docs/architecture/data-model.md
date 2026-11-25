# Data model

!!! abstract "TL;DR"

    - The diagrams show the tables as the migrations in `bootstrap/migrations/versions` create
      them, with the columns that carry the design.
    - A solid line is a real foreign key (same domain). A dotted line is an ID held **by value**,
      which the database does not enforce.
    - A blob shared by many versions is chunked once; a chunk ID is scoped to its version.

- Tables as created by the migrations in `bootstrap/migrations/versions`; the columns shown are the
  ones that carry the design.
- A solid line is a real foreign key (same domain).
- A dotted line is an ID held **by value**, which the database does not enforce.

## Catalog and retrieval

```mermaid
erDiagram
    catalog_libraries ||--o{ catalog_library_versions : "has"
    catalog_libraries ||--o{ catalog_manifests : "has"
    catalog_manifests ||--o{ catalog_manifest_entries : "lists"
    catalog_article_contents ||--o{ catalog_manifest_entries : "shared by blob SHA"

    catalog_libraries {
        text id PK "/owner/repo"
        text title
        text source_url
        json settings "paths, tag rules, chunking"
    }
    catalog_library_versions {
        text library_id PK, FK
        text ref PK "tag, branch or commit"
        text kind
        text commit_sha
        text origin "manual or auto"
    }
    catalog_manifests {
        text id PK
        text library_id FK
        text ref
        text commit_sha
        text state "pending, active, superseded"
    }
    catalog_manifest_entries {
        text manifest_id PK, FK
        text path PK
        text blob_sha FK "with content_version, composite"
        json tags "every tag: imported and manual"
        json manual_tags "tag and the path it was set on"
        json imported_tags "only while manual tags are set"
        json front_matter_tags "imported from front matter; NULL: not recorded"
        json rule_tags "imported from path rules; NULL: not recorded"
        json front_matter
    }
    catalog_article_contents {
        text blob_sha PK "git blob SHA"
        int content_version PK "parser version"
        text content "verbatim Markdown"
    }

    retrieval_chunk_sets ||--o{ retrieval_chunks : "cut into"
    retrieval_chunk_sets ||--o{ retrieval_manifest_chunks : "reused by"
    retrieval_manifests ||--o{ retrieval_manifest_chunks : "indexes"
    retrieval_chunks ||--o| retrieval_vec_N : "embedded in each space"
    retrieval_embedding_spaces ||--|| retrieval_vec_N : "one table per space"

    retrieval_chunk_sets {
        text blob_sha PK
        text config_hash PK "chunking config"
    }
    retrieval_chunks {
        int id PK
        int position
        json heading_path
        text content
    }
    retrieval_manifests {
        text manifest_id PK "by value from catalog"
        text version_id "/owner/repo/ref"
        text library
    }
    retrieval_manifest_chunks {
        text manifest_id PK, FK
        text chunk_id PK "version-scoped hash"
        text article_path
        text prev_chunk_id
        text next_chunk_id
    }
    retrieval_embedding_spaces {
        int id PK "never reused"
        text model
        int dimensions
        text state "building, active, retired"
    }
    retrieval_vec_N {
        int chunk_key PK, FK "retrieval_chunks.id"
        blob embedding "float32 x dimensions"
    }

    catalog_manifests ||..o| retrieval_manifests : "same ID, by value"
```

## Identity and ingestion

```mermaid
erDiagram
    identity_accounts ||--o{ identity_sessions : "signs in with"
    identity_accounts ||--o{ identity_api_tokens : "owns"
    identity_accounts ||..o{ identity_library_grants : "holds roles by ID"
    identity_accounts ||..o{ identity_access_events : "changed access, by ID"
    identity_accounts ||--o| identity_preferences : "saved"

    identity_accounts {
        text id PK
        text username UK
        text password_hash "argon2id"
        text role
        text last_active_at "to the hour"
    }
    identity_sessions {
        text token_hash PK "SHA-256 of the cookie"
        text account_id FK
        text last_used_at
    }
    identity_api_tokens {
        text id PK
        text account_id FK
        text token_hash UK "SHA-256, exd_ prefix"
        text expires_at
    }
    identity_library_grants {
        text library PK "/owner/repo, lower-case"
        text kind PK "user or group"
        text subject PK "account ID or group name"
        text role "viewer, contributor, admin, creator"
    }
    identity_access_events {
        text id PK "UUIDv7: sorts in recording order"
        text library "/owner/repo, lower-case"
        text at
        text actor "account ID; null for the instance"
        text change "library_created, granted, revoked, ownership_transferred, library_deleted"
        text subject "account ID or group name; null for a deletion"
        text role
        text previous_role
    }
    identity_failed_sign_ins {
        text key PK "address:... or username:..."
        int failures
        text last_at "pruned after an hour"
        text previous_at "nullable, restored by a refund"
    }
    identity_known_sign_ins {
        text key PK "username@address"
        text signed_in_at "pruned after 30 days"
    }
    identity_preferences {
        text account_id PK, FK
        json preferences "theme, contrast, text size, ...; a missing key is its default"
    }

    ingestion_jobs {
        text id PK
        text kind "import, refresh, reprocess, rechunk, retag, collect, embed, push"
        text library "by value"
        text version "ref, by value"
        text state "queued, running, succeeded, failed"
        int done
        int total
        json problems
    }
    ingestion_library_credentials {
        text library PK "by value"
        text sealed "Fernet-encrypted token or key"
    }
    ingestion_auto_syncs {
        text library PK "by value"
        text tag_pattern "glob, null: no tag"
        int keep_last
        int interval_minutes
        text checked_at
    }
    ingestion_webhooks {
        text library PK "by value"
        text sealed "Fernet-encrypted secret"
        text created_at
    }
    ingestion_webhook_deliveries {
        text library PK
        text provider PK "github, gitlab, bitbucket"
        text delivery_id PK
        text received_at "pruned after 7 days"
    }
```

## Two derived facts

- A **chunk ID** is a hash of version, article path, heading path, occurrence and content. The same
  section keeps its ID when a branch moves, but another version of the same blob gets another one.
- `retrieval_chunks` is keyed by *(blob SHA, chunking config)*, so a blob shared by many versions is
  chunked once.

## States of a manifest and a job

A manifest and a job each move through a small set of states:

```mermaid
stateDiagram-v2
    direction LR
    state "Manifest (catalog)" as M {
        [*] --> pending: store
        pending --> active: activate (one transaction)
        active --> superseded: a newer manifest activates
        pending --> [*]: discarded on failure
        superseded --> [*]: garbage-collected after the grace period
    }
    state "Job (ingestion)" as J {
        [*] --> queued
        queued --> running: its workflow starts
        running --> succeeded
        running --> failed
        running --> running: resumed after a crash, at its first unfinished step
        running --> queued: no workflow to resume (restart recovery)
    }
```
