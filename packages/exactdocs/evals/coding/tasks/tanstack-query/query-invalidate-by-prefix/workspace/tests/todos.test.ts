import { test } from "node:test";
import assert from "node:assert/strict";
import * as module from "../src/todos.ts";

test("the module exports onTodoAdded", () => {
  assert.ok("onTodoAdded" in module);
});
