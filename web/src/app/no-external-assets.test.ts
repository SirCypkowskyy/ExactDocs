import indexHtml from "../../index.html?raw";
import styles from "./styles.css?raw";

// RUN-03: the page loads nothing from another origin (no Google Fonts, no CDN). Fonts come from
// @fontsource packages that vite bundles into the build.
describe("the page's own entry points", () => {
  it("name no other host", () => {
    expect(indexHtml).not.toMatch(/https?:\/\//);
    expect(styles).not.toMatch(/https?:\/\//);
  });
});
