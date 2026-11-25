import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/config.ts";

test("the module exports ServerConfig", () => {
  assert.ok("ServerConfig" in module);
});
