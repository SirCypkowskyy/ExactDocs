import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/webhook.ts";

test("the module exports Envelope", () => {
  assert.ok("Envelope" in module);
});
