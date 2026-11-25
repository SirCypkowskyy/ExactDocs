import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/rates.ts";

test("the module exports Rates", () => {
  assert.ok("Rates" in module);
});
