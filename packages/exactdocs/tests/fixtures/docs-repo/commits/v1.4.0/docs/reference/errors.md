# Errors

Every failed call returns an error code in the `error.code` field.

## ACME-4021

The card was declined by the issuer. The charge is not retried: ask the customer for another card.

## ACME-5003

The payment network timed out before it answered. The charge may have gone through, so look it up
before you try again.
