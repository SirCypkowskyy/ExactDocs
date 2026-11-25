import { test } from "node:test";
import assert from "node:assert/strict";
import { total } from "../src/pricing.ts";

const isZodError = (error: unknown) =>
  error instanceof Error && Array.isArray((error as { issues?: unknown }).issues);

test("a valid call computes the total", () => {
  assert.equal(total(250, 4, 0.1), 900);
  assert.equal(total(99, 1, 0), 99);
});

test("invalid arguments throw a validation error", () => {
  assert.throws(() => total(-1, 1, 0), isZodError);
  assert.throws(() => total(1, 0, 0), isZodError);
  assert.throws(() => total(1, 1.5, 0), isZodError);
  assert.throws(() => total(1, 1, 2), isZodError);
});
