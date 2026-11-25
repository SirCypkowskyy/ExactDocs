import { test } from "node:test";
import assert from "node:assert/strict";
import { decodeEvent, encodeEvent } from "../src/event.ts";

const AT = "2024-05-01T12:30:00.000Z";

test("an event is decoded with a Date", () => {
  const event = decodeEvent({ name: "launch", at: AT });
  assert.equal(event.name, "launch");
  assert.ok(event.at instanceof Date);
  assert.equal(event.at.getTime(), Date.UTC(2024, 4, 1, 12, 30));
});

test("an invalid event is rejected", () => {
  assert.throws(() => decodeEvent({ name: "launch", at: "yesterday" }));
  assert.throws(() => decodeEvent({ name: "launch", at: 1714566600000 }));
  assert.throws(() => decodeEvent({ at: AT }));
});

test("an event is encoded back to its wire form", () => {
  assert.deepEqual(encodeEvent({ name: "launch", at: new Date(AT) }), { name: "launch", at: AT });
  assert.deepEqual(encodeEvent(decodeEvent({ name: "x", at: AT })), { name: "x", at: AT });
});
