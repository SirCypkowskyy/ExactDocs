---
title: Resilience
description: Keep payments going when the network misbehaves.
tags: [guide]
---

# Resilience

Networks fail. The client can repeat failed calls on your behalf.

## Retry policy

A retry policy says which failures are repeated and how long to wait between attempts.

### retry_policy

Pass `retry_policy` to the client to choose the behaviour:

```python
from acme.payments import Client, RetryPolicy

client = Client(token="sk_test_123", retry_policy=RetryPolicy(max_retries=3, backoff=0.5))
```

| Failure              | Repeated by default |
| -------------------- | ------------------- |
| connection reset     | yes                 |
| HTTP 429 and 503     | yes                 |
| HTTP 4xx (the rest)  | no                  |

A declined card (error `ACME-4021`) is a 4xx failure, so it is never repeated.

### max_retries

`max_retries` limits the attempts after the first call. Use `0` to turn repeating off.

> [!NOTE]
> Charges stay safe to repeat because every call carries an idempotency key.
