import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy*/waitFor give up after this long. The 1 s default is about what the slowest first wait
// takes on an idle machine (a lazy chunk's cold load), so a busy CI runner missed it. It is a
// ceiling, not a delay: a passing wait returns as soon as the element is there.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});

// jsdom has no layout: scrolling is a no-op there.
Element.prototype.scrollIntoView = () => {};

// jsdom has no ResizeObserver; cmdk (the Command list in pickers and filters) measures with it.
if (typeof globalThis.ResizeObserver !== "function") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
