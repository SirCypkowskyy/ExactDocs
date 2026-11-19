// Use the same public API and default headless Chromium as the E2E test.
const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ timeout: 10_000 });
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(10_000);
    await page.setContent('<html><body>ExactDocs browser readiness</body></html>');
    if ((await page.locator('body').innerText()) !== 'ExactDocs browser readiness') {
      throw new Error('Chromium did not render the readiness page');
    }
    await page.screenshot();
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
