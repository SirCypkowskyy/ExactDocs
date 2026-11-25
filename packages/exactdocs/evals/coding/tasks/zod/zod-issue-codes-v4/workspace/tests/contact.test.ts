import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/contact.ts";

test("the module exports summarize", () => {
  assert.ok("summarize" in module);
});
