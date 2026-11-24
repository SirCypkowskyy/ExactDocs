import { beforeEach, describe, expect, it } from "vitest";
import {
  facetParam,
  pageOf,
  parseChoice,
  parseFacet,
  parsePage,
  parseSize,
  parseTableSearch,
  rememberSize,
  sizesFor,
  sortingOf,
  sortOf,
  stringifySearch,
  type TableConfig,
  valuesOf,
} from "./table-search";

const LIST: TableConfig = { id: "things", sortFields: ["name", "created_at"], defaultSort: "-id" };
const STATES = ["queued", "running", "failed"] as const;

beforeEach(() => localStorage.clear());

describe("a table's view in the URL", () => {
  it("keeps the page, size, sort and text the table knows, and drops the rest", () => {
    expect(
      parseTableSearch({ q: "  pay ", sort: "-created_at", page: "3", size: "50" }, LIST),
    ).toEqual({ q: "pay", sort: "-created_at", page: 3, size: 50 });
    expect(parseTableSearch({ q: "", sort: "password", page: "0", size: "7" }, LIST)).toEqual({
      q: undefined,
      sort: undefined,
      page: undefined,
      size: undefined,
    });
  });

  it("reads a page as a whole number from 2; page 1 is the absence of one", () => {
    expect(parsePage(2)).toBe(2);
    expect(parsePage("12")).toBe(12);
    for (const bad of [1, 0, -3, 2.5, "x", "", null, undefined, 2_000_000]) {
      expect(parsePage(bad)).toBeUndefined();
    }
  });

  it("offers 5, 20, 50 and 100 rows, none above a short list's cap", () => {
    expect(sizesFor({})).toEqual([5, 20, 50, 100]);
    expect(sizesFor({ maxRows: 50 })).toEqual([5, 20, 50]);
    expect(sizesFor({ maxRows: 30 })).toEqual([5, 20]);
    expect(sizesFor({ maxRows: 3 })).toEqual([5]);
    expect(parseSize("50")).toBe(50);
    expect(parseSize(100, sizesFor({ maxRows: 50 }))).toBeUndefined();
    expect(parseSize("21")).toBeUndefined();
  });

  it("reads a sort as the API writes it and back", () => {
    expect(sortingOf("-created_at")).toEqual([{ id: "created_at", desc: true }]);
    expect(sortingOf("name")).toEqual([{ id: "name", desc: false }]);
    expect(sortingOf(undefined)).toEqual([]);
    expect(sortOf(sortingOf("-created_at"))).toBe("-created_at");
    expect(sortOf([])).toBeUndefined();
  });
});

describe("pageOf", () => {
  it("shows page 1 at 20 rows when the URL says nothing", () => {
    expect(pageOf({}, LIST)).toEqual({ page: 1, size: 20 });
  });

  it("lets the URL win over the size remembered in this browser", () => {
    rememberSize(LIST, 50);
    expect(pageOf({ size: 5 }, LIST)).toEqual({ page: 1, size: 5 });
    expect(pageOf({}, LIST)).toEqual({ page: 1, size: 50 });
  });

  it("reads a link to page n without a size at the default, so a shared link shows the same rows", () => {
    rememberSize(LIST, 100);
    expect(pageOf({ page: 4 }, LIST)).toEqual({ page: 4, size: 20 });
  });

  it("falls back to the largest size a capped list offers", () => {
    expect(pageOf({}, { ...LIST, maxRows: 3 })).toEqual({ page: 1, size: 5 });
    expect(pageOf({ size: 100 }, { ...LIST, maxRows: 50 })).toEqual({ page: 1, size: 20 });
  });

  it("ignores a remembered size the table no longer offers, and storage that is broken", () => {
    localStorage.setItem("exactdocs-table-sizes", JSON.stringify({ things: 100 }));
    expect(pageOf({}, { ...LIST, maxRows: 50 })).toEqual({ page: 1, size: 20 });
    localStorage.setItem("exactdocs-table-sizes", "{not json");
    expect(pageOf({}, LIST)).toEqual({ page: 1, size: 20 });
  });

  it("remembers sizes per table", () => {
    rememberSize(LIST, 5);
    rememberSize({ ...LIST, id: "others" }, 100);
    expect(JSON.parse(localStorage.getItem("exactdocs-table-sizes") ?? "{}")).toEqual({
      things: 5,
      others: 100,
    });
  });
});

describe("parseFacet", () => {
  it("reads `a,b` and lists alike, in the options' order", () => {
    expect(parseFacet("failed,queued", STATES)).toEqual(["queued", "failed"]);
    expect(parseFacet(["failed", "running"], STATES)).toEqual(["running", "failed"]);
    expect(parseFacet(" failed , queued", STATES)).toEqual(["queued", "failed"]);
  });

  it("drops values nobody offered, so a hand-edited URL never reaches the API", () => {
    expect(parseFacet("failed,lost,DROP TABLE", STATES)).toEqual(["failed"]);
    expect(parseFacet("lost", STATES)).toBeUndefined();
    expect(parseFacet("", STATES)).toBeUndefined();
    expect(parseFacet(42, STATES)).toBeUndefined();
    expect(parseFacet([1, "running", null], STATES)).toEqual(["running"]);
  });

  it("takes one value for a single choice, and writes lists back as the URL does", () => {
    expect(parseChoice("7d,24h", ["24h", "7d"] as const)).toBe("24h");
    expect(parseChoice("never", ["24h", "7d"] as const)).toBeUndefined();
    expect(facetParam(["queued", "failed"])).toBe("queued,failed");
    expect(facetParam([])).toBeUndefined();
    expect(valuesOf("queued,failed")).toEqual(["queued", "failed"]);
    expect(valuesOf(["a", 1])).toEqual(["a"]);
    expect(valuesOf(undefined)).toEqual([]);
  });
});

describe("stringifySearch", () => {
  it("writes a facet's list as `a,b`, which parseFacet reads back", () => {
    const url = stringifySearch({ state: ["queued", "failed"], page: 2, q: "pay ments" });
    expect(url).toBe("?state=queued%2Cfailed&page=2&q=pay+ments");
    const back = new URLSearchParams(url);
    expect(parseFacet(back.get("state"), STATES)).toEqual(["queued", "failed"]);
  });

  it("writes everything else as the router's default does", () => {
    expect(stringifySearch({ ids: [1, 2], tags: ["a,b"], empty: [], flag: true })).toBe(
      `?ids=${encodeURIComponent("[1,2]")}&tags=${encodeURIComponent('["a,b"]')}&empty=${encodeURIComponent("[]")}&flag=true`,
    );
    expect(stringifySearch({})).toBe("");
  });
});
