import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/user.ts";

test("the module exports userOptions", () => {
  assert.ok("userOptions" in module);
});
