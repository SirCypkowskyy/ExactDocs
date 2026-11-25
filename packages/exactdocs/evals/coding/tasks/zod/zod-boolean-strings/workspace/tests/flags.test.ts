import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/flags.ts";

test("the module exports Flags", () => {
  assert.ok("Flags" in module);
});
