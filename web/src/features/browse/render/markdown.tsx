import { ImageOff, Info, Lightbulb, OctagonAlert, TriangleAlert } from "lucide-react";
import type { Token } from "markdown-it";
import { Fragment, type ReactNode, useEffect, useMemo } from "react";
import { CodeBlock } from "./code-block";
import { anchorsOf, inertMdx, md, type Variant, variantOf } from "./parse";
import "./prose.css";
import { classifyLink } from "./urls";

/** What the renderer needs to know about where the article lives. */
export interface Where {
  /** The article's repository path: relative links and images are resolved against its folder. */
  path: string;
  /** The article's title: a leading `# Title` that repeats it is not shown twice. */
  title: string;
  /** The image's bytes at the commit, or undefined: a private library never gets one (alt text only). */
  imageUrl: (repoPath: string) => string | undefined;
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

let keys = 0;

function tree(tokens: readonly Token[]): Node[] {
  const root: Node[] = [];
  const stack: Node[][] = [root];
  for (const token of tokens) {
    if (token.nesting === -1) {
      stack.pop();
      continue;
    }
    const node: Node = { key: keys++, token, children: token.children ? tree(token.children) : [] };
    (stack.at(-1) ?? root).push(node);
    if (token.nesting === 1) stack.push(node.children);
  }
  return root;
}

const ICONS = { note: Info, tip: Lightbulb, warning: TriangleAlert, danger: OctagonAlert };
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
  const variant: Variant = variantOf(kind);
  const Icon = ICONS[variant];
  const head = (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span>{title || titled(kind)}</span>
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

interface Ctx {
  where: Where;
  /** The anchors of the article's headings; none inside an admonition (it is not part of the chunks). */
  anchors: ReturnType<typeof anchorsOf> | null;
}

function many(nodes: readonly Node[], ctx: Ctx): ReactNode[] {
  return nodes.map((node) => <Fragment key={node.key}>{one(node, ctx)}</Fragment>);
}

function link(node: Node, ctx: Ctx) {
  const { where } = ctx;
  const target = classifyLink(where.path, attr(node.token, "href"));
  const kids = many(node.children, ctx);
  switch (target.kind) {
    case "hash":
      return <a href={target.href}>{kids}</a>;
    case "external":
      return (
        <a href={target.href} target="_blank" rel="noopener noreferrer">
          {kids}
        </a>
      );
    case "doc":
      return where.docLink(target.path, target.hash, kids);
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

function image(token: Token, { where }: Ctx) {
  const alt = token.content;
  const target = classifyLink(where.path, attr(token, "src"));
  // Only the repository's own files are loaded, at the commit; nothing is fetched from elsewhere.
  const url = target.kind === "file" ? where.imageUrl(target.path) : undefined;
  if (url) {
    return <img src={url} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" />;
  }
  return (
    <span className="doc-noimage">
      <ImageOff aria-hidden="true" className="size-4 shrink-0" />
      <span>{alt || "Image"}</span>
    </span>
  );
}

function heading(node: Node, ctx: Ctx) {
  const found = ctx.anchors?.get(node.token);
  const level = Number(node.token.tag.slice(1));
  // The page's own headings are h1 (library) and h2 (article): the document's start at h3.
  const Tag = `h${Math.min(level + 2, 6)}` as "h3";
  const repeatsTitle =
    level === 1 && found?.text.toLowerCase() === ctx.where.title.trim().toLowerCase();
  return (
    <Tag id={found?.anchor || undefined} className={`doc-h doc-h${level}`} hidden={repeatsTitle}>
      {many(node.children, ctx)}
      {found?.anchor ? (
        <a href={`#${found.anchor}`} className="doc-anchor" aria-label={`Link to ${found.text}`}>
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
      return token.hidden ? kids() : <p>{kids()}</p>;
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
          {many(tree(md.parse(token.content, {})), { where: ctx.where, anchors: null })}
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
        <li className="doc-task">
          <input
            type="checkbox"
            checked={task === "done"}
            disabled
            aria-label={task === "done" ? "Done" : "Not done"}
          />
          <div>{kids()}</div>
        </li>
      );
    }
    case "fence":
      return <CodeBlock code={token.content} language={fenceLanguage(token.info)} />;
    case "code_block":
      return <CodeBlock code={token.content} />;
    case "html_block":
      return <CodeBlock code={token.content} language="html" />;
    case "hr":
      return <hr />;
    case "table_open":
      return (
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a table wider than the screen scrolls
        <section className="doc-table" aria-label="Table" tabIndex={0}>
          <table>{kids()}</table>
        </section>
      );
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
 * only from the repository itself.
 */
export function Markdown({ source, mdx, where }: { source: string; mdx: boolean; where: Where }) {
  const parsed = useMemo(() => {
    const tokens = md.parse(mdx ? inertMdx(source) : source, {});
    return { nodes: tree(tokens), anchors: anchorsOf(tokens) };
  }, [source, mdx]);
  // A link to `#section` opens the article on it, once the text is there.
  useEffect(() => {
    try {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (id) document.getElementById(id)?.scrollIntoView();
    } catch {
      // a malformed fragment points at nothing
    }
  }, []);
  return <div className="doc">{many(parsed.nodes, { where, anchors: parsed.anchors })}</div>;
}
