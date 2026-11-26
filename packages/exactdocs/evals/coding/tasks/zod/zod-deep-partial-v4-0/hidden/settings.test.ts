import { test } from "node:test";
import assert from "node:assert/strict";
import { SettingsPatch } from "../src/settings.ts";

test("a patch may set a single nested field", () => {
  assert.deepEqual(SettingsPatch.parse({ editor: { tabs: { size: 4 } } }), { editor: { tabs: { size: 4 } } });
  assert.deepEqual(SettingsPatch.parse({}), {});
  assert.deepEqual(SettingsPatch.parse({ theme: "dark" }), { theme: "dark" });
});

test("the fields a patch sets are still validated", () => {
  assert.throws(() => SettingsPatch.parse({ editor: { tabs: { size: "4" } } }));
  assert.throws(() => SettingsPatch.parse({ theme: "blue" }));
  assert.throws(() => SettingsPatch.parse({ editor: { fontSize: 12.5 } }));
});
