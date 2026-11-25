import { test } from "node:test";
import assert from "node:assert/strict";
import { Flags } from "../src/flags.ts";

test("true and false spellings, in any case", () => {
  for (const value of ["true", "TRUE", "1", "yes", "On"]) {
    assert.equal(Flags.parse({ DEBUG: value }).DEBUG, true, value);
  }
  for (const value of ["false", "0", "NO", "off"]) {
    assert.equal(Flags.parse({ DEBUG: value }).DEBUG, false, value);
  }
});

test("an absent flag is false", () => {
  assert.deepEqual(Flags.parse({}), { DEBUG: false, CACHE: false });
  assert.deepEqual(Flags.parse({ CACHE: "yes" }), { DEBUG: false, CACHE: true });
});

test("another value is rejected", () => {
  assert.throws(() => Flags.parse({ DEBUG: "maybe" }));
  assert.throws(() => Flags.parse({ CACHE: "" }));
});
