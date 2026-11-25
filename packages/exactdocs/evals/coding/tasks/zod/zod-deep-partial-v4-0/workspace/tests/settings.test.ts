import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/settings.ts";

test("the module exports Settings", () => {
  assert.ok("Settings" in module);
});
