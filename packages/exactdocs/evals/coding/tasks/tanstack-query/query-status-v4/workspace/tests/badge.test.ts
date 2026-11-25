import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/badge.ts";

test("the module exports badge", () => {
  assert.ok("badge" in module);
});
