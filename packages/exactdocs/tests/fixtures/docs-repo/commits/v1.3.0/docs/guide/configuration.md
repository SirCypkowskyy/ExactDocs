# Configuration

The client reads its settings from keyword arguments, then from the environment.

## Options

| Option            | Default | Meaning                              |
| ----------------- | ------- | ------------------------------------ |
| `api_key`         | none    | the secret key used to sign requests |
| `connection_pool` | `10`    | how many HTTP connections to keep    |
| `idempotencyKey`  | none    | a caller-supplied key for one charge |

## Connection pool

`connection_pool` caps the number of open HTTP connections. Raise it for batch jobs.

## Command line

The `acme` command accepts `--dry-run` to validate a charge without sending it, and
`--timeout 30` to wait at most thirty seconds.
