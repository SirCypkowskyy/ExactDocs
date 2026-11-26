// The benchmark history tables (docs/benchmark/*/history.md, #616): sort by any column, filter by
// a column's values or a date range, and chart one metric over time. The table itself is the
// Markdown one `just bench-pages` writes, so without this script (or for ExactDocs' importer) it
// reads as it is. The state lives in the address: ?sort=recall-5&dir=asc&chunking=default&from=...
(() => {
  const RUN = new Set(["Date", "Commit", "Golden"]); // what a run is, not what a series is
  const COLOURS = ["--xd-route", "--xd-tint-note", "--xd-tint-tip", "--xd-tint-danger", "--xd-tint-warning", "--xd-muted"];
  const SVG = "http://www.w3.org/2000/svg";

  const number = (text) => {
    const t = text.replace(/[,%\s]/g, "");
    return t !== "" && Number.isFinite(Number(t)) ? Number(t) : null;
  };
  const slug = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  };
  const svg = (tag, attrs = {}) => {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };

  function enhance(root) {
    const table = root.querySelector("table");
    if (!table || root.dataset.ready) return;
    root.dataset.ready = "true";
    const heads = [...table.tHead.rows[0].cells];
    const names = heads.map((th) => th.textContent.trim());
    const keys = names.map(slug);
    const body = table.tBodies[0];
    const rows = [...body.rows].map((tr, index) => ({ tr, index, text: [...tr.cells].map((td) => td.textContent.trim()) }));
    const numeric = names.map((_, c) => rows.some((r) => r.text[c] !== "") && rows.every((r) => r.text[c] === "" || number(r.text[c]) !== null));
    const dateCol = names.indexOf("Date");
    const params = new URLSearchParams(location.search);
    const state = {
      sort: Math.max(keys.indexOf(params.get("sort")), 0),
      desc: params.has("sort") ? params.get("dir") !== "asc" : true,
      filters: new Map(),
      from: params.get("from") || "",
      to: params.get("to") || "",
      metric: params.get("metric") || "",
    };

    // ---- filters
    const form = el("form", { className: "bench-history__filters", role: "search", ariaLabel: "Filter the runs" });
    form.addEventListener("submit", (e) => e.preventDefault());
    names.forEach((name, c) => {
      if (numeric[c] || c === dateCol) return;
      const values = [...new Set(rows.map((r) => r.text[c]).filter(Boolean))].sort();
      if (values.length < 2 || values.length > 50) return;
      const select = el("select", { name: keys[c] }, el("option", { value: "", textContent: "All" }), ...values.map((v) => el("option", { value: v, textContent: v })));
      if (values.includes(params.get(keys[c]))) {
        select.value = params.get(keys[c]);
        state.filters.set(c, select.value);
      }
      select.addEventListener("change", () => {
        select.value ? state.filters.set(c, select.value) : state.filters.delete(c);
        update();
      });
      form.append(el("label", {}, el("span", { textContent: name }), select));
    });
    if (dateCol >= 0) {
      for (const [key, label] of [["from", "From"], ["to", "To"]]) {
        const input = el("input", { type: "date", name: key, value: state[key] });
        input.addEventListener("change", () => {
          state[key] = input.value;
          update();
        });
        form.append(el("label", {}, el("span", { textContent: label }), input));
      }
    }
    const reset = el("button", { type: "button", className: "md-button", textContent: "Reset" });
    reset.addEventListener("click", () => {
      form.reset();
      state.filters.clear();
      state.from = state.to = "";
      update();
    });
    form.append(reset);
    const count = el("p", { className: "bench-history__count", ariaLive: "polite" });

    // ---- sorting: a button in each header, aria-sort on the sorted one
    heads.forEach((th, c) => {
      const button = el("button", { type: "button", className: "bench-history__sort" }, ...th.childNodes);
      button.addEventListener("click", () => {
        state.desc = state.sort === c ? !state.desc : numeric[c] || c === dateCol;
        state.sort = c;
        update();
      });
      th.append(button);
    });

    // ---- chart
    const metrics = names.map((n, c) => (numeric[c] ? n : null)).filter(Boolean);
    const defaultMetric = metrics.find((m) => /recall@5|accuracy|coverage/i.test(m)) || metrics[0] || "";
    if (!metrics.includes(state.metric)) state.metric = defaultMetric;
    const pick = el("select", { name: "metric" }, ...metrics.map((m) => el("option", { value: m, textContent: m })));
    pick.value = state.metric;
    pick.addEventListener("change", () => {
      state.metric = pick.value;
      update();
    });
    const plot = el("div", { className: "bench-history__plot" });
    const chart = el("div", { className: "bench-history__chart" }, el("label", {}, el("span", { textContent: "Chart" }), pick), plot);

    root.prepend(form, count, ...(dateCol >= 0 && metrics.length ? [chart] : []));

    function update() {
      const shown = rows.filter((r) =>
        [...state.filters].every(([c, v]) => r.text[c] === v) &&
        (!state.from || r.text[dateCol] >= state.from) &&
        (!state.to || r.text[dateCol] <= state.to));
      const c = state.sort;
      const sorted = [...rows].sort((a, b) => {
        const [x, y] = numeric[c] ? [number(a.text[c]), number(b.text[c])] : [a.text[c] || null, b.text[c] || null];
        if (x === y) return a.index - b.index;
        if (x === null) return 1; // empty cells last, either way
        if (y === null) return -1;
        const order = numeric[c] ? x - y : x.localeCompare(y, undefined, { numeric: true });
        return state.desc ? -order : order;
      });
      for (const r of sorted) {
        r.tr.hidden = !shown.includes(r);
        body.append(r.tr);
      }
      heads.forEach((th, k) => (k === c ? th.setAttribute("aria-sort", state.desc ? "descending" : "ascending") : th.removeAttribute("aria-sort")));
      count.textContent = `Showing ${shown.length} of ${rows.length} results.`;
      draw(shown);

      const next = new URLSearchParams();
      if (c !== Math.max(dateCol, 0) || !state.desc) next.set("sort", keys[c]);
      if (next.has("sort")) next.set("dir", state.desc ? "desc" : "asc");
      for (const [k, v] of state.filters) next.set(keys[k], v);
      if (state.from) next.set("from", state.from);
      if (state.to) next.set("to", state.to);
      if (state.metric !== defaultMetric) next.set("metric", state.metric);
      const query = next.toString();
      history.replaceState(history.state, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
    }

    function draw(shown) {
      plot.replaceChildren();
      const m = names.indexOf(state.metric);
      if (m < 0 || dateCol < 0) return;
      const dims = names.map((n, k) => (!numeric[k] && !RUN.has(n) ? k : -1)).filter((k) => k >= 0);
      const series = new Map();
      for (const r of shown) {
        const y = number(r.text[m]);
        if (y === null) continue;
        const name = dims.map((k) => r.text[k]).filter(Boolean).join(" · ");
        if (!series.has(name)) series.set(name, new Map());
        // one point a day: rows are in recorded order, so a day's last result wins
        series.get(name).set(r.text[dateCol], { x: Date.parse(r.text[dateCol]), y, date: r.text[dateCol] });
      }
      const points = [...series.values()].flatMap((days) => [...days.values()]);
      if (new Set(points.map((p) => p.x)).size < 2) {
        plot.append(el("p", { textContent: "The results in view are from one day: nothing to chart. Widen the filters." }));
        return;
      }
      const [W, H, L, R, T, B] = [640, 220, 48, 12, 10, 26];
      const xs = points.map((p) => p.x);
      const ys = points.map((p) => p.y);
      const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
      let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
      if (y0 === y1) [y0, y1] = [y0 - 1, y1 + 1];
      const px = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
      const py = (y) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
      const pct = rows.some((r) => r.text[m].endsWith("%"));
      const label = (y) => (pct ? `${y.toFixed(1)}%` : y.toLocaleString(undefined, { maximumFractionDigits: 3 }));
      const view = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${names[m]} over time, ${series.size} series; the table holds every value` });
      for (const y of [y0, (y0 + y1) / 2, y1]) {
        view.append(svg("line", { x1: L, x2: W - R, y1: py(y), y2: py(y), class: "bench-history__grid" }));
        const t = svg("text", { x: L - 6, y: py(y) + 4, "text-anchor": "end" });
        t.textContent = label(y);
        view.append(t);
      }
      for (const [x, anchor] of [[x0, "start"], [x1, "end"]]) {
        const t = svg("text", { x: px(x), y: H - 6, "text-anchor": anchor });
        t.textContent = new Date(x).toISOString().slice(0, 10);
        view.append(t);
      }
      const coloured = series.size <= COLOURS.length;
      const legend = el("ul", { className: "bench-history__legend" });
      [...series].forEach(([name, days], i) => {
        const ps = [...days.values()];
        const colour = coloured ? `var(${COLOURS[i]})` : "var(--xd-muted)";
        ps.sort((a, b) => a.x - b.x);
        const g = svg("g", { style: `color: ${colour}` });
        g.append(svg("polyline", { points: ps.map((p) => `${px(p.x)},${py(p.y)}`).join(" "), class: "bench-history__line" }));
        for (const p of ps) {
          const dot = svg("circle", { cx: px(p.x), cy: py(p.y), r: 3.5 });
          const tip = svg("title");
          tip.textContent = `${name || names[m]}, ${p.date}: ${label(p.y)}`;
          dot.append(tip);
          g.append(dot);
        }
        view.append(g);
        if (coloured) legend.append(el("li", { style: `--colour: ${colour}`, textContent: name || names[m] }));
      });
      plot.append(view);
      if (coloured) plot.append(legend);
      else plot.append(el("p", { textContent: `${series.size} series; filter the table to tell them apart by colour, or point at a dot for its name.` }));
    }

    update();
  }

  const run = () => document.querySelectorAll(".bench-history").forEach(enhance);
  // navigation.instant swaps the page without a reload; document$ fires on every page
  if (typeof document$ !== "undefined") document$.subscribe(run);
  else document.addEventListener("DOMContentLoaded", run);
})();
