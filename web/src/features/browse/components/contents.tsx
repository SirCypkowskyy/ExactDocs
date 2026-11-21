import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";
import { cn } from "@/shared/lib/utils";

/*
 * "On this page": the article's h2 and h3 sections, read from the rendered text, with the one in
 * view marked. A sticky column beside the text from xl up (after the free shadcnblocks
 * "Blogpost 2" layout), a disclosure under the title below that.
 */

interface Heading {
  anchor: string;
  text: string;
  level: 2 | 3;
}

const SELECTOR = ".doc > .doc-h2[id]:not([hidden]), .doc > .doc-h3[id]:not([hidden])";

function read(root: HTMLElement): Heading[] {
  return [...root.querySelectorAll<HTMLElement>(SELECTOR)].map((el) => ({
    anchor: el.id.replace(/^doc-/, ""),
    // The heading's own "#" link is not part of its name.
    text: [...el.childNodes]
      .filter((n) => !(n instanceof HTMLElement && n.classList.contains("doc-anchor")))
      .map((n) => n.textContent ?? "")
      .join("")
      .trim(),
    level: el.classList.contains("doc-h2") ? 2 : 3,
  }));
}

/** The headings of the rendered article; follows the text as it renders (the renderer is lazy). */
function useHeadings(root: RefObject<HTMLElement | null>): Heading[] {
  const [headings, setHeadings] = useState<Heading[]>([]);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const update = () => {
      const next = read(el);
      setHeadings((prev) =>
        prev.length === next.length && prev.every((h, i) => h.anchor === next[i]?.anchor)
          ? prev
          : next,
      );
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(el, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [root]);
  return headings;
}

/** The section being read: the last heading above the top fifth of the viewport. */
function useActive(headings: Heading[]): string | undefined {
  const [active, setActive] = useState<string>();
  useEffect(() => {
    if (headings.length === 0 || typeof IntersectionObserver === "undefined") return;
    const elements = headings
      .map((h) => document.getElementById(`doc-${h.anchor}`))
      .filter((e): e is HTMLElement => e !== null);
    const observer = new IntersectionObserver(
      () => {
        const line = window.innerHeight * 0.2;
        let current = elements[0]?.id;
        for (const e of elements) if (e.getBoundingClientRect().top <= line) current = e.id;
        setActive(current?.replace(/^doc-/, ""));
      },
      { rootMargin: "0px 0px -80% 0px", threshold: [0, 1] },
    );
    for (const e of elements) observer.observe(e);
    return () => observer.disconnect();
  }, [headings]);
  return active;
}

interface ContentsProps {
  article: RefObject<HTMLElement | null>;
  owner: string;
  repo: string;
  version: string;
  path: string;
  tags: string | undefined;
}

function List({
  headings,
  active,
  link,
}: {
  headings: Heading[];
  active: string | undefined;
  link: Omit<ContentsProps, "article">;
}) {
  return (
    <ul className="border-l border-border">
      {headings.map((h) => {
        const current = h.anchor === active;
        return (
          <li key={h.anchor}>
            <Link
              to="/libraries/$owner/$repo"
              params={{ owner: link.owner, repo: link.repo }}
              search={{ version: link.version, path: link.path, tags: link.tags }}
              hash={h.anchor}
              resetScroll={false}
              aria-current={current ? "location" : undefined}
              className={cn(
                "-ml-px flex min-h-11 items-center border-l py-1 pr-2 text-body text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring lg:min-h-7",
                h.level === 2 ? "pl-3" : "pl-6",
                current ? "border-route font-medium text-foreground" : "border-transparent",
              )}
            >
              <span className="line-clamp-2">{h.text}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** The sticky column (xl and up). Renders nothing for an article with fewer than two sections. */
export function ContentsRail(props: ContentsProps) {
  const headings = useHeadings(props.article);
  const active = useActive(headings);
  if (headings.length < 2) return null;
  return (
    <nav
      aria-label="On this page"
      className="sticky top-17 hidden max-h-[calc(100dvh-6rem)] overflow-y-auto xl:block"
    >
      <p className="mb-2 text-small font-medium text-muted-foreground">On this page</p>
      <List headings={headings} active={active} link={props} />
    </nav>
  );
}

/** The same list folded under the title, for screens without the column. */
export function ContentsDisclosure(props: ContentsProps) {
  const headings = useHeadings(props.article);
  const active = useActive(headings);
  if (headings.length < 2) return null;
  return (
    <details className="group mt-4 rounded-lg border border-border xl:hidden">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-3 text-body font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden="true"
          className="size-4 text-muted-foreground transition-transform duration-(--dur) ease-(--ease-out) group-open:rotate-90 motion-reduce:transition-none"
        />
        On this page
        <span className="text-small font-normal text-muted-foreground">
          {headings.length} sections
        </span>
      </summary>
      <nav aria-label="On this page" className="px-3 pb-3">
        <List headings={headings} active={active} link={props} />
      </nav>
    </details>
  );
}
