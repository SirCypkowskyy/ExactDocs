// The screenshots of the README and the documentation, from the real UI: `just screenshots` runs
// this after screenshots.py has started and seeded the server. Each picture is taken in the light
// and the dark theme, at 1440 px wide and twice the pixels; screenshots.py writes them as WebP.
import { readFileSync } from "node:fs";
import { type BrowserContext, expect, type Page, test } from "@playwright/test";
import { settled, signIn } from "./helpers";

const env = (name: string) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set: run \`just screenshots\``);
  return value;
};
const SERVER = env("EXACTDOCS_URL");
const USER = env("SHOTS_USER");
const PASSWORD = env("SHOTS_PASSWORD");
const OUT = "shots/screenshots";
const WIDTH = 1440;

// A fixed clock. The server stamps what it does with the real time, so every time the API
// returns from this run is moved to as if the seeding had started at SEEDED_AT, and the browser's
// clock stands three and a half hours later: "3 hours ago", "Nov 2, 2026", on every run.
const STARTED_AT = Date.parse(env("SHOTS_STARTED_AT"));
const SEEDED_AT = Date.parse(env("SHOTS_SEEDED_AT"));
const NOW = SEEDED_AT + 3.5 * 3600_000;
const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;
// A token's prefix is the start of its random secret: each one gets a fixed one from its name.
const TOKEN_PREFIX = /^exd_[A-Za-z0-9_-]+$/;

function fixedPrefix(name: string): string {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  let hash = 7;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) % 1_000_003;
  return `exd_${Array.from({ length: 4 }, (_, i) => letters[(hash >> (i * 5)) % letters.length]).join("")}`;
}

function stable(value: unknown): unknown {
  if (typeof value === "string" && ISO_TIME.test(value)) {
    const t = Date.parse(value);
    return t >= STARTED_AT - 60_000 ? new Date(t - STARTED_AT + SEEDED_AT).toISOString() : value;
  }
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    const entries = Object.entries(value).map(([k, v]) => [k, stable(v)] as const);
    const object = Object.fromEntries(entries);
    if (typeof object.prefix === "string" && TOKEN_PREFIX.test(object.prefix)) {
      object.prefix = fixedPrefix(String(object.name));
    }
    return object;
  }
  return value;
}

async function stableContext(context: BrowserContext) {
  await context.clock.setFixedTime(NOW);
  await context.route("**/api/v1/**", async (route) => {
    // Fetched from Node, which knows nothing of the browser's mapping of localhost:3000.
    const url = route.request().url().replace(/^http:\/\/localhost:3000/, SERVER);
    const response = await route.fetch({ url });
    if (!(response.headers()["content-type"] ?? "").startsWith("application/json")) {
      return route.fulfill({ response });
    }
    return route.fulfill({ response, json: stable(await response.json()) });
  });
}

async function ready(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  await settled(page);
}

/** The viewport, `height` CSS pixels tall, as `<name>-<scheme>.png`. */
async function shoot(page: Page, name: string, scheme: string, height: number) {
  await page.setViewportSize({ width: WIDTH, height });
  await ready(page);
  await page.screenshot({ path: `${OUT}/${name}-${scheme}.png`, animations: "disabled" });
}

/** A `query-docs` call of screenshots.py and the text blocks of its reply. */
interface Reply {
  library: string;
  version: string;
  query: string;
  texts: string[];
}

const CHUNKS = "\n\n--------------------------------\n\n";
const escape = (text: string) =>
  text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

/**
 * Two `query-docs` replies side by side, each the call and its first chunk verbatim, with the
 * lines that differ between them highlighted (but the chunk ID, which differs with its text).
 */
function mcpFigure(replies: Reply[]): string {
  const firsts = replies.map((r) => r.texts[1].split(CHUNKS)[0].trimEnd().split("\n"));
  const cards = replies.map((reply, i) => {
    const others = new Set(firsts.filter((_, j) => j !== i).flat());
    const lines = firsts[i].map((line) => {
      const differs = line.trim() !== "" && !others.has(line) && !line.startsWith("Chunk: ");
      return `<span class="${differs ? "line differs" : "line"}">${escape(line) || " "}</span>`;
    });
    const chunks = reply.texts[1].split(CHUNKS).length;
    return `<section class="card">
      <header><span class="mono">/acme/payments</span> <b class="mono">${reply.version}</b></header>
      <div class="call mono"><b>query-docs</b>
        <span class="key">libraryId</span>"${escape(reply.library)}"
        <span class="key">query</span>"${escape(reply.query)}"</div>
      <p class="note">The reply: an untrusted-content notice, then ${chunks} chunks, best first. The first, verbatim:</p>
      <pre class="mono">${lines.join("")}</pre>
    </section>`;
  });
  return `<style>
    #figure { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; width: 1200px;
      padding: 32px; box-sizing: border-box; background: var(--frame); color: var(--foreground);
      font-family: var(--font-sans); }
    #figure .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 24px; min-width: 0; }
    #figure .mono, #figure pre { font-family: var(--font-mono); }
    #figure header { font-size: 16px; margin-bottom: 16px; color: var(--muted-foreground); }
    #figure header b { color: var(--foreground); margin-left: 8px; }
    #figure .call { display: grid; grid-template-columns: auto 1fr; gap: 4px 24px; font-size: 14px;
      background: var(--raised); border-radius: 8px; padding: 14px 16px; }
    #figure .call b { grid-column: 1 / -1; }
    #figure .key { color: var(--muted-foreground); }
    #figure .note { font-size: 13px; color: var(--muted-foreground); margin: 16px 0 8px; }
    #figure pre { margin: 0; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
    #figure .line { display: block; padding: 0 6px; margin: 0 -6px; border-radius: 4px; }
    #figure .differs { background: var(--route-soft); }
  </style><div id="figure">${cards.join("")}</div>`;
}

const READER = "/libraries/acme/payments?version=v1.4.0&path=docs%2Fguide%2Fresilience.md";

test("the README's and the documentation's screenshots", async ({ browser }) => {
  const replies: Reply[] = JSON.parse(readFileSync(env("SHOTS_MCP"), "utf-8"));
  for (const scheme of ["light", "dark"] as const) {
    // Nothing stored: the theme follows the system's, set before the first paint.
    const context = await browser.newContext({ colorScheme: scheme });
    await stableContext(context);
    const page = await context.newPage();
    await signIn(page, USER, PASSWORD);

    await page.goto("/");
    await expect(page.getByRole("link", { name: "Acme Store", exact: true })).toBeVisible();
    await shoot(page, "libraries", scheme, 520);

    await page.goto("/libraries/acme/payments");
    await page.getByRole("button", { name: /Change version/ }).click();
    await expect(page.getByRole("list", { name: "Versions" })).toBeVisible();
    await shoot(page, "library", scheme, 720);

    await page.goto(READER);
    await expect(page.locator(".doc-code")).toBeVisible();
    await shoot(page, "reader", scheme, 900);

    await page.goto("/search?q=retry");
    await expect(page.locator("[data-result]").first()).toBeVisible();
    await shoot(page, "search", scheme, 900);

    await page.goto("/playground");
    await page.getByLabel("Query", { exact: true }).fill("how do I retry failed calls");
    await page.getByRole("checkbox", { name: "/acme/payments" }).check();
    await page.getByLabel("Mode", { exact: true }).selectOption("hybrid");
    await page.getByRole("checkbox", { name: "Compare two modes side by side" }).check();
    await page.getByLabel("Compare with", { exact: true }).selectOption("bm25");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByRole("list", { name: /results$/ })).toHaveCount(2);
    await shoot(page, "playground", scheme, 1200);

    await page.goto("/ai");
    await expect(page.getByText("100%")).toBeVisible();
    await shoot(page, "ai", scheme, 1120);

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Connect an agent" })).toBeVisible();
    await expect(page.getByText("Claude Code", { exact: true })).toBeVisible();
    await shoot(page, "connect", scheme, 800);

    // The MCP figure: two real replies, drawn with the UI's own colours and type.
    await page.evaluate((html) => {
      document.body.innerHTML = html;
    }, mcpFigure(replies));
    await ready(page);
    await page.locator("#figure").screenshot({ path: `${OUT}/mcp-${scheme}.png` });
    await context.close();
  }
});
