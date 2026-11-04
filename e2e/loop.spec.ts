import { expect, test } from "@playwright/test";

const FIXTURE_REPO_URL = process.env.FIXTURE_REPO_URL;
if (!FIXTURE_REPO_URL) throw new Error("FIXTURE_REPO_URL is not set: run the test through e2e/run.py");
const PASSWORD = "a long passphrase here";

test("setup, add the fixture repository, browse an article, search a term", async ({ page }) => {
  // setup: a fresh instance sends every visitor to it
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await page.getByLabel("Username").fill("ada");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Repeat the password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account and sign in" }).click();
  await expect(page.getByRole("heading", { name: "Libraries" })).toBeVisible();

  // add the fixture repository over HTTP git
  await page.goto("/libraries/new");
  await page.getByLabel("Repository address").fill(FIXTURE_REPO_URL);
  await page.getByRole("button", { name: "Check repository" }).click();
  await expect(page.getByText("Found on a git server")).toBeVisible();
  await page.getByLabel("Version to import").selectOption({ label: "v1.4.0" });
  await page.getByRole("button", { name: "Add library" }).click();
  await expect(page.getByText(/^\d+ files imported/)).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: "shots/1-imported.png" });

  // browse: the Resilience article renders (markdown, highlighted code, table, callout)
  await page.goto("/libraries/fixture/docs-repo?version=v1.4.0");
  await page.getByRole("treeitem", { name: "docs", exact: true }).click();
  await page.getByRole("treeitem", { name: "guide", exact: true }).click();
  await page.getByRole("treeitem", { name: "Resilience" }).click();
  await expect(page).toHaveURL(/resilience\.md/);
  await expect(page.getByRole("heading", { name: "Resilience" }).first()).toBeVisible();
  await expect(page.locator(".doc-code")).toBeVisible();
  await expect(page.locator(".doc-table table")).toBeVisible();
  await expect(page.locator(".doc-callout")).toBeVisible();
  await page.screenshot({ path: "shots/2-article.png" });

  // search: the result opens its section
  await page.getByRole("searchbox").fill("retry_policy");
  await page.keyboard.press("Enter");
  const hit = page.locator("[data-result]").first();
  await expect(hit).toContainText("resilience.md");
  await page.screenshot({ path: "shots/3-search.png" });
  await hit.click();
  const section = page.locator("#doc-retry_policy");
  await expect(page).toHaveURL(/#retry_policy$/);
  await expect(section).toBeInViewport();
  await expect(section).toHaveClass(/doc-target/);
  await page.screenshot({ path: "shots/4-section.png" });
});
