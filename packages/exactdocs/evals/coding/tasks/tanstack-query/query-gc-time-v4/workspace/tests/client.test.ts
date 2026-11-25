import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/client.ts";

test("the module exports createClient", () => {
  assert.ok("createClient" in module);
});
