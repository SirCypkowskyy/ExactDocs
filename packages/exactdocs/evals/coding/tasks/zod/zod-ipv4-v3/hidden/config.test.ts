import { test } from "node:test";
import assert from "node:assert/strict";
import { parseConfig } from "../src/config.ts";

test("a valid config is parsed", () => {
  assert.deepEqual(parseConfig({ name: "api", host: "10.0.0.7", port: 8080 }), {
    name: "api",
    host: "10.0.0.7",
    port: 8080,
  });
});

test("the host must be an IPv4 address", () => {
  for (const host of ["::1", "example.org", "10.0.0", "256.1.1.1"]) {
    assert.throws(() => parseConfig({ name: "api", host, port: 80 }), host);
  }
});

test("the port must be an integer from 1 to 65535", () => {
  for (const port of [0, 65536, 80.5, "80"]) {
    assert.throws(() => parseConfig({ name: "api", host: "10.0.0.7", port }), String(port));
  }
});
