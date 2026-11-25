import { test } from "node:test";
import assert from "node:assert/strict";
import { ListQuery } from "../src/query.ts";

test("the page size is converted to a number", () => {
  assert.equal(ListQuery.parse({ pageSize: "50" }).pageSize, 50);
});

test("an absent page size is 20", () => {
  assert.equal(ListQuery.parse({}).pageSize, 20);
  assert.equal(ListQuery.parse({ search: "lamp" }).pageSize, 20);
});

test("a page size that is not digits is rejected", () => {
  assert.throws(() => ListQuery.parse({ pageSize: "ten" }));
  assert.throws(() => ListQuery.parse({ pageSize: "-5" }));
});
