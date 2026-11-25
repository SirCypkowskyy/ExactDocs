import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/query.ts";

test("the module exports ListQuery", () => {
  assert.ok("ListQuery" in module);
});
