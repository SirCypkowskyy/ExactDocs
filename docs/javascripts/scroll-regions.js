// A wide table (or a row of content tabs) scrolls sideways inside a box the theme adds. Only a
// box that overflows becomes a tab stop, named after the table's caption or the nearest heading,
// so the arrow keys can scroll it (#619). Without JavaScript the theme adds no box and nothing changes.
(() => {
  const name = (box) => {
    const caption = box.querySelector("caption");
    if (caption) return caption.textContent.trim();
    const heading = document.evaluate("preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]", box, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    const text = heading ? [...heading.childNodes].filter((n) => !n.classList?.contains("headerlink")).map((n) => n.textContent).join("").trim() : "";
    return text || document.title;
  };
  // Two regions under one heading get "(2)", "(3)": a landmark's name must be unique on the page.
  const unique = (text) => {
    const taken = new Set([...document.querySelectorAll("[role=region][aria-label]")].map((r) => r.ariaLabel));
    let n = 1, label = text;
    while (taken.has(label)) label = `${text} (${++n})`;
    return label;
  };
  const sync = (box) => {
    if (box.scrollWidth > box.clientWidth) {
      if (box.tabIndex === 0) return;
      Object.assign(box, { tabIndex: 0, role: "region", ariaLabel: unique(name(box)) });
    } else if (box.tabIndex === 0) {
      box.removeAttribute("tabindex");
      box.removeAttribute("role");
      box.removeAttribute("aria-label");
    }
  };
  // The box's width changes with the window, and its table's with bench-history.js's filters.
  const observer = new ResizeObserver((entries) => entries.forEach((e) => sync(e.target.closest(".md-typeset__scrollwrap, .tabbed-labels"))));
  const run = () => {
    observer.disconnect();
    document.querySelectorAll(".md-typeset__scrollwrap, .md-typeset .tabbed-labels").forEach((box) => {
      sync(box);
      observer.observe(box);
      if (box.firstElementChild) observer.observe(box.firstElementChild);
    });
  };
  // navigation.instant swaps the page without a reload; document$ fires on every page
  if (typeof document$ !== "undefined") document$.subscribe(run);
  else document.addEventListener("DOMContentLoaded", run);
})();
