import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/pricing.ts";

test("the module exports total", () => {
  assert.ok("total" in module);
});
