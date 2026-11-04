# Naming conventions

How identifiers are spelled across Acme Payments.

## snake_case

Python parameters and fields use `snake_case`, for example `api_key`.

## camelCase

JSON payloads use `camelCase`, for example `idempotencyKey`.

## --flag

Command-line options start with two dashes: a `--flag` takes effect for one run.

## pkg.mod.fn

Dotted paths name a function inside a module inside a package, as in `pkg.mod.fn`.
