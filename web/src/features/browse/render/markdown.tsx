import {
  ImageOff,
  Info,
  Lightbulb,
  OctagonAlert,
  Square,
  SquareCheck,
  TriangleAlert,
} from "lucide-react";
import type { Token } from "markdown-it";
import { Fragment, type ReactNode, useEffect, useMemo, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { messages } from "../messages";
import { CodeBlock } from "./code-block";
import { type Budget, createBudget } from "./limits";
import { anchorsOf, inertMdx, md, type Variant, variantOf } from "./parse";
import "./prose.css";
import { classifyLink } from "./urls";

/** What the renderer needs to know about where the article lives. */
export interface Where {
  /** The article's repository path: relative links and images are resolved against its folder. */
  path: string;
  /** The article's title: a leading `# Title` that repeats it is not shown twice. */
  title: string;
  /**
   * Where to load a repository image from, best first: ExactDocs's imported copy, then (public
   * libraries only) the host's raw file. A source that fails (404 on a version imported without
   * images) falls through to the next; when none is left the alt text shows.
   */
  imageSources: (repoPath: string) => string[];
  /** The page of a file that is not an article, at the commit. */
  fileUrl: (repoPath: string) => string | undefined;
  /** A link to another article of this version: the app's own `Link`, so it navigates without a page load. */
  docLink: (repoPath: string, hash: string, children: ReactNode) => ReactNode;
}

interface Node {
  key: number;
  token: Token;
  children: Node[];
}

/** Tokens to a tree. An admonition's body is parsed here too, once, with the rest of the document. */
function tree(tokens: readonly Token[], count = { next: 0 }): Node[] {
  const root: Node[] = [];
  const stack: Node[][] = [root];
  for (const token of tokens) {
    if (token.nesting === -1) {
      stack.pop();
      continue;
    }
    const inner = token.children
      ? token.children
      : token.type === "admonition"
        ? md.parse(token.content, {})
        : [];
    const node: Node = { key: count.next++, token, children: [] };
    (stack.at(-1) ?? root).push(node);
    node.children = tree(inner, count);
    if (token.nesting === 1) stack.push(node.children);
  }
  return root;
}

/** The renderer's own words (labels around the text, never the text itself). */
type Texts = (typeof messages)["en"]["render"];

const ICONS = { note: Info, tip: Lightbulb, warning: TriangleAlert, danger: OctagonAlert };
/** A callout without a title shows its kind as the file wrote it: that is the document's word. */
const titled = (kind: string) => kind.charAt(0).toUpperCase() + kind.slice(1);

function Callout({
  kind,
  title,
  children,
  collapsible,
  open,
}: {
  kind: string;
  title?: string | undefined;
  children: ReactNode;
  collapsible?: boolean;
  open?: boolean;
}) {
  const t = useMessages(messages).render;
  const variant: Variant = variantOf(kind);
  const Icon = ICONS[variant];
  const head = (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span>
        {/* A title replaces the type's name: screen readers still hear which kind of note it is. */}
        {title ? <span className="sr-only">{t.variant[variant]}: </span> : null}
        {title || titled(kind)}
      </span>
    </>
  );
  return collapsible ? (
    <details className={`doc-callout doc-${variant}`} open={open}>
      <summary>{head}</summary>
      <div className="doc-callout-body">{children}</div>
    </details>
  ) : (
    <div role="note" className={`doc-callout doc-${variant}`}>
      <p className="doc-callout-title">{head}</p>
      <div className="doc-callout-body">{children}</div>
    </div>
  );
}

const attr = (token: Token, name: string) => String(token.attrGet(name) ?? "");
const fenceLanguage = (info: string) => /[\w+#-]+/.exec(info.split(/\s/, 1)[0] ?? "")?.[0];

/** The text of a subtree, for a table's name. */
const textOf = (node: Node): string =>
  node.token.type === "text" || node.token.type === "code_inline"
    ? node.token.content
    : node.children.map(textOf).join("");

/** Headings get `doc-<anchor>` ids: the anchor itself (the chunk's) is only ever a URL fragment. */
const idOf = (anchor: string) => `doc-${anchor}`;

interface Ctx {
  where: Where;
  /** The anchors of the article's headings; none inside an admonition (it is not part of the chunks). */
  anchors: ReturnType<typeof anchorsOf> | null;
  budget: Budget;
  /** The anchor the URL points at, if any. */
  target: string;
  t: Texts;
}

function many(nodes: readonly Node[], ctx: Ctx): ReactNode[] {
  return nodes.map((node) => <Fragment key={node.key}>{one(node, ctx)}</Fragment>);
}

/** A same-page `#x` link. Heading ids are `doc-<anchor>`, so the browser's own jump finds nothing: scroll there ourselves. */
function hashLink(href: string, kids: ReactNode) {
  return (
    <a
      href={href}
      onClick={() => {
        try {
          document.getElementById(idOf(decodeURIComponent(href.slice(1))))?.scrollIntoView();
        } catch {
          // a malformed fragment points at nothing
        }
      }}
    >
      {kids}
    </a>
  );
}

/** A paragraph whose only content is one image (whitespace aside): the image stands as a block. */
const isFigure = (node: Node) => {
  const inline = node.children[0]?.children ?? [];
  const solid = inline.filter(
    (c) => !(c.token.type === "softbreak" || (c.token.type === "text" && !c.token.content.trim())),
  );
  return solid.length === 1 && solid[0]?.token.type === "image";
};

function link(node: Node, ctx: Ctx) {
  const { where } = ctx;
  const target = classifyLink(where.path, attr(node.token, "href"));
  const kids = many(node.children, ctx);
  switch (target.kind) {
    case "hash":
      return hashLink(target.href, kids);
    case "external":
      return (
        <a href={target.href} target="_blank" rel="noopener noreferrer">
          {kids}
        </a>
      );
    case "doc":
      // A link to this article's own heading: the hash may already be the URL's, so the router
      // would not scroll again. Treat it as a same-page link, which scrolls on every click.
      return target.path === where.path && target.hash
        ? hashLink(target.hash, kids)
        : where.docLink(target.path, target.hash, kids);
    case "file": {
      const url = where.fileUrl(target.path);
      return url ? (
        <a href={url} target="_blank" rel="noopener noreferrer">
          {kids}
        </a>
      ) : (
        <>{kids}</>
      );
    }
    default:
      return <>{kids}</>;
  }
}

function NoImage({ alt }: { alt: string }) {
  const t = useMessages(messages).render;
  return (
    <span className="doc-noimage">
      <ImageOff aria-hidden="true" className="size-4 shrink-0" />
      <span>{t.noImage(alt)}</span>
    </span>
  );
}

/** An image that tries each source in turn, then shows its alt text. Size is not known: CSS bounds it. */
function Img({ sources, alt }: { sources: readonly string[]; alt: string }) {
  // `failed` counts the sources that errored. The caller keys this by `sources`, so a changed list
  // (a late access answer adding the host fallback) starts again at the first.
  const [failed, setFailed] = useState(0);
  const src = sources[failed];
  if (!src) return <NoImage alt={alt} />;
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed((n) => n + 1)}
    />
  );
}

function image(token: Token, { where }: Ctx) {
  const alt = token.content;
  const target = classifyLink(where.path, attr(token, "src"));
  // Only the repository's own files are loaded; nothing is fetched from elsewhere.
  const sources = target.kind === "file" ? where.imageSources(target.path) : [];
  return <Img key={sources.join("\n")} sources={sources} alt={alt} />;
}

function heading(node: Node, ctx: Ctx) {
  const found = ctx.anchors?.get(node.token);
  const level = Number(node.token.tag.slice(1));
  // The page's own headings are h1 (library) and h2 (article): the document's start at h3.
  const Tag = `h${Math.min(level + 2, 6)}` as "h3";
  const repeatsTitle =
    level === 1 && found?.text.toLowerCase() === ctx.where.title.trim().toLowerCase();
  const aimed = Boolean(found?.anchor) && found?.anchor === ctx.target;
  return (
    <Tag
      id={found?.anchor ? idOf(found.anchor) : undefined}
      className={`doc-h doc-h${level}${aimed ? " doc-target" : ""}`}
      hidden={repeatsTitle}
    >
      {many(node.children, ctx)}
      {found?.anchor ? (
        <a href={`#${found.anchor}`} className="doc-anchor" aria-label={ctx.t.linkTo(found.text)}>
          #
        </a>
      ) : null}
    </Tag>
  );
}

function one(node: Node, ctx: Ctx): ReactNode {
  const { token } = node;
  const kids = () => many(node.children, ctx);
  switch (token.type) {
    case "inline":
      return kids();
    case "text":
      return token.content;
    case "softbreak":
      return " ";
    case "hardbreak":
      return <br />;
    case "code_inline":
      return <code>{token.content}</code>;
    case "html_inline":
      return token.content; // shown as the text it is
    case "em_open":
      return <em>{kids()}</em>;
    case "strong_open":
      return <strong>{kids()}</strong>;
    case "s_open":
      return <s>{kids()}</s>;
    case "link_open":
      return link(node, ctx);
    case "image":
      return image(token, ctx);
    case "paragraph_open":
      if (node.children[0]?.children.length === 0) return null;
      if (token.hidden) return kids();
      return isFigure(node) ? <p className="doc-figure">{kids()}</p> : <p>{kids()}</p>;
    case "heading_open":
      return heading(node, ctx);
    case "blockquote_open": {
      const alert = token.meta?.alert as string | undefined;
      return alert ? <Callout kind={alert}>{kids()}</Callout> : <blockquote>{kids()}</blockquote>;
    }
    case "admonition": {
      const meta = token.meta as { title?: string; collapsible: boolean; open: boolean };
      return (
        <Callout
          kind={token.info}
          title={meta.title}
          collapsible={meta.collapsible}
          open={meta.open}
        >
          {many(node.children, { ...ctx, anchors: null })}
        </Callout>
      );
    }
    case "bullet_list_open":
      return <ul>{kids()}</ul>;
    case "ordered_list_open": {
      const start = Number(attr(token, "start") || 1);
      return <ol start={start === 1 ? undefined : start}>{kids()}</ol>;
    }
    case "list_item_open": {
      const task = token.meta?.task as "todo" | "done" | undefined;
      if (!task) return <li>{kids()}</li>;
      return (
        <li className={task === "done" ? "doc-task doc-task-done" : "doc-task"}>
          {task === "done" ? (
            <SquareCheck role="img" aria-label={ctx.t.done} />
          ) : (
            <Square role="img" aria-label={ctx.t.notDone} />
          )}
          <div>{kids()}</div>
        </li>
      );
    }
    case "fence":
      return (
        <CodeBlock code={token.content} language={fenceLanguage(token.info)} budget={ctx.budget} />
      );
    case "code_block":
      return <CodeBlock code={token.content} />;
    case "html_block":
      return <CodeBlock code={token.content} language="html" budget={ctx.budget} />;
    case "hr":
      return <hr />;
    case "table_open": {
      const first = node.children[0]?.children[0]?.children[0];
      const name = first ? textOf(first).trim() : "";
      return (
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a table wider than the screen scrolls
        <section className="doc-table" aria-label={ctx.t.table(name)} tabIndex={0}>
          <table>{kids()}</table>
        </section>
      );
    }
    case "thead_open":
      return <thead>{kids()}</thead>;
    case "tbody_open":
      return <tbody>{kids()}</tbody>;
    case "tr_open":
      return <tr>{kids()}</tr>;
    case "th_open":
    case "td_open": {
      const align = /text-align:(left|right|center)/.exec(attr(token, "style"))?.[1];
      const Cell = token.type === "th_open" ? "th" : "td";
      return <Cell className={align ? `doc-${align}` : undefined}>{kids()}</Cell>;
    }
    default:
      return null;
  }
}

/**
 * An article as elements. Nothing from the repository is parsed as HTML or run: raw HTML and
 * MDX components show as text or code, links keep to http(s) and mailto, and an image is loaded
 * only from the repository itself. `hash` is the URL's fragment (a chunk anchor, as in a search
 * result): the heading it names is scrolled to and marked.
 */
export function Markdown({
  source,
  mdx,
  where,
  hash = "",
}: {
  source: string;
  mdx: boolean;
  where: Where;
  hash?: string;
}) {
  const t = useMessages(messages).render;
  const parsed = useMemo(() => {
    const tokens = md.parse(mdx ? inertMdx(source) : source, {});
    return { nodes: tree(tokens), anchors: anchorsOf(tokens), budget: createBudget() };
  }, [source, mdx]);
  const target = useMemo(() => {
    try {
      return decodeURIComponent(hash.replace(/^#/, ""));
    } catch {
      return ""; // a malformed fragment points at nothing
    }
  }, [hash]);
  useEffect(() => {
    if (target) document.getElementById(idOf(target))?.scrollIntoView();
  }, [target]);
  return <div className="doc">{many(parsed.nodes, { where, target, t, ...parsed })}</div>;
}
