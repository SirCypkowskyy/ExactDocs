import { test } from "node:test";
import assert from "node:assert/strict";
import { parseEnvelope } from "../src/webhook.ts";

test("a delivery without a payload", () => {
  assert.deepEqual(parseEnvelope({ type: "ping" }), { type: "ping" });
});

test("a delivery with any payload", () => {
  assert.deepEqual(parseEnvelope({ type: "order", payload: { id: 7 } }), { type: "order", payload: { id: 7 } });
  assert.deepEqual(parseEnvelope({ type: "order", payload: null }), { type: "order", payload: null });
});

test("the type is required and not empty", () => {
  assert.throws(() => parseEnvelope({ payload: 1 }));
  assert.throws(() => parseEnvelope({ type: "" }));
});
