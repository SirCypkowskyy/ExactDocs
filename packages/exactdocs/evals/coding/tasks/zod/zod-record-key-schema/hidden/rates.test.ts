import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRates } from "../src/rates.ts";

test("rates are parsed", () => {
  assert.deepEqual(parseRates({ EUR: 0.92, "Japanese yen": 151.2 }), { EUR: 0.92, "Japanese yen": 151.2 });
  assert.deepEqual(parseRates({}), {});
});

test("a rate must be a positive number", () => {
  assert.throws(() => parseRates({ EUR: 0 }));
  assert.throws(() => parseRates({ EUR: "0.92" }));
  assert.throws(() => parseRates([0.92]));
});
