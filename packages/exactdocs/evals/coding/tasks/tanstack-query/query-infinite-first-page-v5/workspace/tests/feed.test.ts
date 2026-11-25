import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/feed.ts";

test("the module loads", () => {
  assert.equal(typeof module, "object");
});
