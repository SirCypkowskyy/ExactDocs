import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/signup.ts";

test("the module exports problems", () => {
  assert.ok("problems" in module);
});
