# Authentication

Every request carries a bearer token in the `Authorization` header.

## Creating a token

Open the dashboard, choose **API keys** and create a token. Copy it right away: it is shown once.

## Using a token

```python
from acme.payments import Client

client = Client(token="sk_test_123")
```

| Scope     | Allows                        |
| --------- | ----------------------------- |
| `read`    | list payments and customers   |
| `charge`  | create and capture payments   |
| `refund`  | refund captured payments      |

## Rotating tokens

Create the new token first, deploy it, then delete the old one.
