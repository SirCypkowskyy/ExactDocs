# Payments quickstart

Accept a first payment in **five minutes**. This page covers the *happy path*, ~~the old way~~ and
where to go next. See the [auth guide](./auth.md#api-keys), the [overview](#overview) or the
[source of the schema](../schema/payments.json). The [docs site](https://example.com/docs?a=1&b=2) is
the long version, and <https://example.com/bare> is an autolink.

## Overview

Every request is made with `curl`, `fetch()` or an SDK. Set `ACME_API_KEY` first.

> Idempotency keys are kept for 24 hours. A retry with the same key returns the original response.

### Install

```bash
pnpm add @acme/payments
export ACME_API_KEY="sk_test_123"   # never commit this
```

### Create a payment

```ts
import { Acme } from "@acme/payments";

const acme = new Acme({ apiKey: process.env.ACME_API_KEY });

export async function charge(amount: number): Promise<string> {
  const payment = await acme.payments.create({ amount, currency: "eur" });
  return payment.id; // pay_01H…
}
```

```python
from acme import Acme

client = Acme(api_key=os.environ["ACME_API_KEY"])
payment = client.payments.create(amount=1200, currency="eur", metadata={"order": 42})
print(f"created {payment.id}")
```

```json
{ "id": "pay_01H8", "amount": 1200, "paid": true, "tags": ["a", "b"], "fee": null }
```

```yaml
retries:
  max: 3
  backoff: exponential # seconds
```

```diff
- const acme = new Acme(key);
+ const acme = new Acme({ apiKey: key });
```

```nolang-here
plain text, not highlighted: <b>not bold</b>
```

## Reference

| Field    | Type     |  Required | Description                                                                 |
| :------- | :------- | --------: | :-------------------------------------------------------------------------- |
| `amount` | integer  |       yes | Smallest currency unit. 1200 is 12.00 EUR.                                  |
| `currency` | string |       yes | Three-letter ISO code, lower case.                                          |
| `metadata` | object |        no | Up to 20 keys; values are strings of at most 500 characters.                |
| `description` | string | no     | Shown on the receipt and in the dashboard, up to 1,000 characters.          |

### Steps

1. Create the payment.
2. Confirm it on the client.
   - Cards confirm at once.
   - Bank transfers confirm later, by webhook.
3. Fulfil the order.

- [x] Create a test key
- [ ] Go live
- [ ] Tell the team

### Pictures

![Dashboard overview](./img/dashboard.png)

![Logo from elsewhere](https://tracker.example.net/pixel.png)

![Escapes the repo](../../../../etc/passwd.png)

---

## Usage

Duplicate heading, to check the anchors.

## Usage

A very long heading follows.

### Configuring the retry policy for webhook deliveries that fail repeatedly across regions and providers

Hard break after this line  
and a soft break
here.

#### Level four
##### Level five
###### Level six
