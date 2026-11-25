import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/keys.ts";

test("the module exports cacheIdOf", () => {
  assert.ok("cacheIdOf" in module);
});
