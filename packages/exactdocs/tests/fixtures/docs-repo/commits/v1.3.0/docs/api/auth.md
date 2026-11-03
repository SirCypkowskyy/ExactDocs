---
title: Authentication API
description: Endpoints that issue and revoke API tokens.
tags: [auth]
---

# Authentication API

Endpoints that issue and revoke tokens.

## Issue a token

`POST /v1/tokens` returns a new token and its scopes.

```http
POST /v1/tokens
Content-Type: application/json

{"scopes": ["read", "charge"]}
```

## Revoke a token

`DELETE /v1/tokens/{id}` revokes a token immediately.
