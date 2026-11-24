import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  lastJumpPage,
  type PageRequest,
  pageQueryOptions,
  type ServerSource,
} from "./server-pages";

/**
 * A list API over `count` rows: `limit` up to 200, an opaque forward-only cursor (`o<n>`), and
 * the total. With `paging: "offset"` it also takes an `offset`. Every request is recorded.
 */
function api(count: number, paging: "cursor" | "offset" = "cursor") {
  const rows = Array.from({ length: count }, (_, i) => `row ${i + 1}`);
  const asked: Omit<PageRequest, "signal">[] = [];
  const source: ServerSource<string> = {
    key: ["things", paging],
    paging,
    fetchPage: async ({ limit, cursor, offset }) => {
      asked.push({ limit, cursor, ...(offset !== undefined && { offset }) });
      if (limit > 200) throw new Error(`limit ${limit} is over the API's 200`);
      if (offset !== undefined && cursor) throw new Error("cursor_with_offset");
      if (offset !== undefined && offset > 10_000) throw new Error(`offset ${offset} over 10000`);
      const start = offset ?? (cursor ? Number(cursor.slice(1)) : 0);
      const page = rows.slice(start, start + limit);
      return {
        rows: page,
        total: rows.length,
        nextCursor: start + limit < rows.length ? `o${start + limit}` : null,
      };
    },
  };
  return { source, asked, rows };
}

const load = (client: QueryClient, source: ServerSource<string>, page: number, size: number) =>
  client.fetchQuery(pageQueryOptions(source, page, size));

describe("numbered pages over a cursor API", () => {
  it("asks for the first page once and keeps where the next one starts", async () => {
    const { source, asked } = api(45);
    const page = await load(new QueryClient(), source, 1, 20);
    expect(asked).toEqual([{ limit: 20, cursor: null }]);
    expect(page.rows[0]).toBe("row 1");
    expect(page).toMatchObject({ total: 45, offset: 0, nextCursor: "o20" });
  });

  it("reaches a page nobody has seen in one request while that fits in 200 rows", async () => {
    const { source, asked } = api(500);
    const page = await load(new QueryClient(), source, 3, 20);
    expect(asked).toEqual([{ limit: 60, cursor: null }]);
    expect(page.rows).toHaveLength(20);
    expect(page.rows[0]).toBe("row 41");
    expect(page.rows.at(-1)).toBe("row 60");
  });

  it("walks in steps of 200 to a page further than 200 rows in", async () => {
    const { source, asked } = api(500);
    // Page 15 of 20 rows starts at row 281: one step of 200, then one request for 80 + 20.
    const page = await load(new QueryClient(), source, 15, 20);
    expect(asked).toEqual([
      { limit: 200, cursor: null },
      { limit: 100, cursor: "o200" },
    ]);
    expect(page.rows[0]).toBe("row 281");
    expect(page.rows.at(-1)).toBe("row 300");
    expect(page).toMatchObject({ offset: 280, total: 500, nextCursor: "o300" });
  });

  it("walks a long way at 100 rows a page without ever asking for more than 200", async () => {
    const { source, asked } = api(1_250);
    const page = await load(new QueryClient(), source, 12, 100);
    expect(asked.map((a) => a.limit)).toEqual([200, 200, 200, 200, 200, 200]);
    expect(asked.map((a) => a.cursor)).toEqual([null, "o200", "o400", "o600", "o800", "o1000"]);
    expect(page.rows[0]).toBe("row 1101");
    expect(page.rows.at(-1)).toBe("row 1200");
  });

  it("starts from the nearest cursor a page already in the cache knows", async () => {
    const { source, asked } = api(500);
    const client = new QueryClient();
    await load(client, source, 1, 20);
    await load(client, source, 2, 20);
    asked.length = 0;

    const page = await load(client, source, 4, 20);

    // Page 2 ended at row 40: skip 20 more from its cursor instead of starting over.
    expect(asked).toEqual([{ limit: 40, cursor: "o40" }]);
    expect(page.rows[0]).toBe("row 61");
  });

  it("asks for the next page from the cursor the shown one ended with", async () => {
    const { source, asked } = api(45);
    const client = new QueryClient();
    await load(client, source, 1, 20);
    asked.length = 0;
    const page = await load(client, source, 2, 20);
    expect(asked).toEqual([{ limit: 20, cursor: "o20" }]);
    expect(page.rows[0]).toBe("row 21");
  });

  it("answers an empty page past the end when the list shrank under the walk", async () => {
    const { source } = api(150);
    const page = await load(new QueryClient(), source, 30, 20);
    expect(page.rows).toEqual([]);
    expect(page.total).toBe(150);
    expect(page.nextCursor).toBeNull();
  });

  it("keeps each view's cursors apart", async () => {
    const one = api(500);
    const other = api(500);
    other.source.key = ["things", "other view"];
    const client = new QueryClient();
    await load(client, one.source, 1, 20);
    await load(client, other.source, 3, 20);
    // Nothing from the first view's cache leaks into the second's walk.
    expect(other.asked).toEqual([{ limit: 60, cursor: null }]);
  });
});

describe("numbered pages over an offset API", () => {
  it("reaches any page in one request of one page", async () => {
    const { source, asked } = api(500, "offset");
    const page = await load(new QueryClient(), source, 15, 20);
    expect(asked).toEqual([{ limit: 20, cursor: null, offset: 280 }]);
    expect(page.rows[0]).toBe("row 281");
    expect(page.offset).toBe(280);
  });

  it("asks by offset even when the cache knows a cursor there", async () => {
    const { source, asked } = api(500, "offset");
    const client = new QueryClient();
    await load(client, source, 1, 20);
    await load(client, source, 2, 20);
    expect(asked).toEqual([
      { limit: 20, cursor: null, offset: 0 },
      { limit: 20, cursor: null, offset: 20 },
    ]);
  });

  it("reaches the page at the API's bound by offset", async () => {
    const { source, asked } = api(12_000, "offset");
    const page = await load(new QueryClient(), source, 101, 100);
    expect(asked).toEqual([{ limit: 100, cursor: null, offset: 10_000 }]);
    expect(page.rows[0]).toBe("row 10001");
  });

  it("walks by cursor from the bound to a page past it", async () => {
    const { source, asked } = api(12_000, "offset");
    // Page 520 of 20 starts at row 10,381: 380 rows past the bound, a step of 200, then one more.
    const page = await load(new QueryClient(), source, 520, 20);
    expect(asked).toEqual([
      { limit: 200, cursor: null, offset: 10_000 },
      { limit: 200, cursor: "o10200" },
    ]);
    expect(page.rows[0]).toBe("row 10381");
    expect(page).toMatchObject({ offset: 10_380, total: 12_000, nextCursor: "o10400" });
  });

  it("goes on past the bound from the cursor the shown page ended with", async () => {
    const { source, asked } = api(12_000, "offset");
    const client = new QueryClient();
    await load(client, source, 501, 20);
    asked.length = 0;
    const page = await load(client, source, 502, 20);
    expect(asked).toEqual([{ limit: 20, cursor: "o10020" }]);
    expect(page.rows[0]).toBe("row 10021");
  });

  it("knows the farthest page a jump reaches at each size", () => {
    expect(lastJumpPage(api(1, "offset").source, 20)).toBe(501);
    expect(lastJumpPage(api(1, "offset").source, 100)).toBe(101);
    expect(lastJumpPage({ ...api(1, "offset").source, maxOffset: 40 }, 20)).toBe(3);
    expect(lastJumpPage(api(1).source, 20)).toBe(1);
  });
});
