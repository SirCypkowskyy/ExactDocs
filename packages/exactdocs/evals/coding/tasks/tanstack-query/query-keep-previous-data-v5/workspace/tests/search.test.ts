import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/search.ts";

test("the module exports searchOptions", () => {
  assert.ok("searchOptions" in module);
});
