import { test } from "node:test";
import assert from "node:assert/strict";
import { problems } from "../src/signup.ts";

test("a valid form has no problem", () => {
  assert.deepEqual(problems({ username: "ada", age: 36 }), []);
});

test("a missing username says it is required", () => {
  assert.deepEqual(problems({ age: 36 }), ["username: Username is required"]);
});

test("a username of another type says it must be text", () => {
  assert.deepEqual(problems({ username: 42, age: 36 }), ["username: Username must be text"]);
  assert.deepEqual(problems({ username: null, age: 36 }), ["username: Username must be text"]);
});
