import { test } from "node:test";
import assert from "node:assert/strict";
import { summarize } from "../src/contact.ts";

test("a valid contact has no problem", () => {
  assert.deepEqual(summarize({ name: "Ada", email: "ada@example.com" }), []);
});

test("each kind of problem", () => {
  assert.deepEqual(summarize({ email: "ada@example.com" }), ["name: missing"]);
  assert.deepEqual(summarize({ name: "", email: "ada@example.com" }), ["name: empty"]);
  assert.deepEqual(summarize({ name: "Ada", email: "ada at example" }), ["email: bad-email"]);
  assert.deepEqual(summarize({ name: 7, email: "ada@example.com" }), ["name: wrong-type"]);
});

test("several problems at once", () => {
  assert.deepEqual(summarize({ name: "", email: "nope" }).sort(), ["email: bad-email", "name: empty"]);
});
