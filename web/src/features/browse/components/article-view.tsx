import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, ChevronRight } from "lucide-react";
import { Fragment, lazy, Suspense, useState } from "react";
import { HttpError } from "@/shared/lib/http";
import { accessQueryOptions, articleQueryOptions } from "../api/browse-queries";
import {
  type Article,
  commitUrl,
  HOST_NAMES,
  type LibraryDetail,
  safeHref,
  shortSha,
  type Version,
} from "../model/browse";
import { blobUrl, rawUrl } from "../render/urls";

// The renderer (Markdown parser and all) is its own chunk: the tree and the overview do not wait for it.
const Markdown = lazy(() => import("../render/markdown").then((m) => ({ default: m.Markdown })));

interface ArticleViewProps {
  owner: string;
  repo: string;
  library: LibraryDetail;
  version: Version;
  path: string;
  tags: string | undefined;
}

/** A proof link: one underline under the whole label, so "Commit" and the SHA read as one. */
const external =
  "group inline-flex min-h-11 items-center gap-1 rounded-md px-1 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8";
const underline =
  "underline decoration-mark/40 underline-offset-4 group-hover:decoration-mark group-focus-visible:decoration-mark";
const action =
  "inline-flex h-11 items-center rounded-md px-5 text-sm font-medium outline-none transition-[background-color,transform] duration-150 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.97]";
const secondary = `${action} bg-secondary text-secondary-foreground [@media(hover:hover)]:hover:bg-accent`;

/** A repository path, allowed to break after each slash instead of in the middle of a word. */
function PathText({ path }: { path: string }) {
  return path.split("/").map((part, i, all) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: the same segment can repeat in a path
    <Fragment key={i}>
      {part}
      {i < all.length - 1 && (
        <>
          /<wbr />
        </>
      )}
    </Fragment>
  ));
}

/** Where the exact commit lives: the file at the commit, and the commit itself. */
export function CommitLinks({
  library,
  version,
  fileUrl,
}: {
  library: LibraryDetail;
  version: Version;
  fileUrl?: string | null | undefined;
}) {
  const host = HOST_NAMES[library.host];
  const file = safeHref(fileUrl);
  const commit = commitUrl(library.host, library.source_url, version.commit_sha);
  return (
    <div className="-ml-1 flex flex-wrap items-center gap-x-4 gap-y-0">
      {file && (
        <a href={file} target="_blank" rel="noopener noreferrer" className={external}>
          <span className={underline}>View file on {host ?? "the host"}</span>
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
          <span className="sr-only">
            at commit {shortSha(version.commit_sha)} (opens a new tab)
          </span>
        </a>
      )}
      {commit ? (
        <a href={commit} target="_blank" rel="noopener noreferrer" className={external}>
          <span className={underline}>
            Commit <code className="font-mono">{shortSha(version.commit_sha)}</code>
          </span>
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
          <span className="sr-only">(opens a new tab)</span>
        </a>
      ) : (
        <p className="px-1 text-sm text-muted-foreground" title={version.commit_sha}>
          Commit <code className="font-mono">{shortSha(version.commit_sha)}</code>
          {" · no link, this host is not recognised"}
        </p>
      )}
    </div>
  );
}

// Same blocks as the loaded article, so the content lands where the placeholder was.
function ArticleSkeleton() {
  return (
    <div aria-hidden="true" className="max-w-3xl space-y-4 motion-safe:animate-pulse">
      <span className="block h-4 w-2/3 max-w-sm rounded bg-muted-foreground/[0.14]" />
      <span className="block h-8 w-1/2 rounded bg-muted-foreground/[0.14]" />
      <span className="block h-5 w-40 rounded bg-muted-foreground/[0.14]" />
      <span className="block h-8 w-72 max-w-full rounded bg-muted-foreground/[0.14]" />
      <span className="mt-5 block h-64 rounded-lg bg-muted-foreground/[0.14]" />
    </div>
  );
}

function NotInVersion({
  owner,
  repo,
  library,
  version,
  path,
  tags,
  suggestions,
}: ArticleViewProps & { suggestions: readonly string[] }) {
  const newest = library.default_version;
  const link =
    "flex h-11 items-center justify-between gap-2 rounded-md bg-secondary px-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring [@media(hover:hover)]:hover:bg-accent";
  return (
    <div className="fade-in max-w-3xl">
      <h2 className="font-serif text-2xl font-semibold tracking-tight">
        Not in <span className="font-mono text-[0.9em]">{version.ref}</span>
      </h2>
      <p className="mt-2 text-pretty text-muted-foreground">
        {version.ref} has no{" "}
        <code className="font-mono text-sm text-foreground [overflow-wrap:anywhere]">
          <PathText path={path} />
        </code>
        . It may have been added later, moved or removed.
      </p>
      {suggestions.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-medium">Close matches in {version.ref}</h3>
          <ul className="mt-2 space-y-1.5">
            {suggestions.map((s) => (
              <li key={s}>
                <Link
                  to="/libraries/$owner/$repo"
                  params={{ owner, repo }}
                  search={{ version: version.ref, path: s, tags }}
                  className={link}
                >
                  <span className="min-w-0 [overflow-wrap:anywhere]">
                    <PathText path={s} />
                  </span>
                  <ChevronRight
                    aria-hidden="true"
                    className="size-4 shrink-0 text-muted-foreground"
                  />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-6 flex flex-wrap gap-2">
        <Link
          to="/libraries/$owner/$repo"
          params={{ owner, repo }}
          search={{ version: version.ref, tags }}
          className={secondary}
        >
          Show the root of {version.ref}
        </Link>
        {newest && newest !== version.ref && (
          <Link
            to="/libraries/$owner/$repo"
            params={{ owner, repo }}
            search={{ version: newest, path, tags }}
            className={secondary}
          >
            Open this path in {newest}
          </Link>
        )}
      </div>
    </div>
  );
}

const toggle =
  "inline-flex h-11 min-w-20 items-center justify-center rounded-[5px] px-3 text-sm font-medium outline-none transition-[background-color,color] duration-150 focus-visible:ring-2 focus-visible:ring-ring lg:h-8";

/** Rendered text or the file as stored: the source is always one click away. */
function ViewToggle({
  view,
  onChange,
}: {
  view: "rendered" | "source";
  onChange: (view: "rendered" | "source") => void;
}) {
  return (
    <fieldset className="m-0 inline-flex min-w-0 rounded-md border-0 bg-secondary p-0.5">
      <legend className="sr-only">View</legend>
      {(["rendered", "source"] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={() => onChange(v)}
          className={`${toggle} cursor-pointer capitalize ${
            view === v
              ? "bg-card text-foreground ring-1 ring-border"
              : "text-muted-foreground [@media(hover:hover)]:hover:text-foreground"
          }`}
        >
          {v === "rendered" ? "Rendered" : "Source"}
        </button>
      ))}
    </fieldset>
  );
}

/** Placeholder lines for the renderer's chunk; the article shell is already on screen. */
function TextSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-3 motion-safe:animate-pulse">
      {["w-11/12", "w-full", "w-4/5", "w-2/3"].map((w) => (
        <span key={w} className={`block h-4 rounded bg-muted-foreground/[0.14] ${w}`} />
      ))}
    </div>
  );
}

function RenderedText({
  article,
  owner,
  repo,
  library,
  version,
  tags,
}: {
  article: Article;
  owner: string;
  repo: string;
  library: LibraryDetail;
  version: Version;
  tags: string | undefined;
}) {
  const access = useQuery(accessQueryOptions(owner, repo));
  // Until the library is known to be public, no image is requested from the host.
  const isPublic = access.data?.private === false;
  const doc = (path: string, hash: string) => ({
    to: "/libraries/$owner/$repo" as const,
    params: { owner, repo },
    search: { version: version.ref, path, tags },
    ...(hash.length > 1 ? { hash: hash.slice(1) } : {}),
  });
  return (
    <Suspense fallback={<TextSkeleton />}>
      <Markdown
        source={article.content}
        mdx={/\.mdx$/i.test(article.path)}
        where={{
          path: article.path,
          title: article.title,
          imageUrl: (p) =>
            isPublic ? rawUrl(library.host, library.source_url, version.commit_sha, p) : undefined,
          fileUrl: (p) => blobUrl(library.host, library.source_url, version.commit_sha, p),
          docLink: (path, hash, children) => <Link {...doc(path, hash)}>{children}</Link>,
        }}
      />
    </Suspense>
  );
}

function Body({
  article,
  owner,
  repo,
  library,
  version,
  tags,
}: {
  article: Article;
  owner: string;
  repo: string;
  library: LibraryDetail;
  version: Version;
  tags: string | undefined;
}) {
  const [view, setView] = useState<"rendered" | "source">("rendered");
  return (
    <article className="min-w-0 max-w-3xl">
      <p className="font-mono text-[13px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
        <PathText path={article.path} />
      </p>
      <h2 className="mt-1 font-serif text-2xl font-semibold tracking-tight text-balance [overflow-wrap:anywhere] sm:text-3xl">
        {article.title}
      </h2>
      {article.tags.length > 0 && (
        // Plain text, not chips: chips are the filter's controls and these do nothing.
        <ul
          aria-label="Tags"
          className="mt-2 flex flex-wrap gap-x-3 text-[13px] text-muted-foreground"
        >
          {article.tags.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      <div className="mt-2">
        <CommitLinks library={library} version={version} fileUrl={article.source_url} />
      </div>
      <div className="mt-4">
        <ViewToggle view={view} onChange={setView} />
      </div>
      {view === "rendered" ? (
        <section aria-label="Article text" className="mt-6">
          <RenderedText
            article={article}
            owner={owner}
            repo={repo}
            library={library}
            version={version}
            tags={tags}
          />
        </section>
      ) : (
        // The file as stored, set as text.
        <section aria-label="Source text" className="mt-6">
          <pre
            // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable text must be reachable by keyboard
            tabIndex={0}
            className="overflow-x-auto rounded-lg bg-secondary/60 p-4 font-mono text-[14px] leading-[1.7] break-words whitespace-pre-wrap outline-none [tab-size:4] focus-visible:ring-2 focus-visible:ring-ring sm:p-6"
          >
            {article.content}
          </pre>
        </section>
      )}
    </article>
  );
}

/** The article pane: loading, the text, "not in this version" with suggestions, or an error. */
export function ArticleView(props: ArticleViewProps) {
  const { owner, repo, library, version, path } = props;
  const query = useQuery(
    articleQueryOptions({ owner, repo, ref: version.ref, sha: version.commit_sha }, path),
  );
  if (query.isPending) {
    return (
      <div role="status" aria-busy="true">
        <span className="sr-only">Loading {path}</span>
        <ArticleSkeleton />
      </div>
    );
  }
  if (query.isError) {
    const error = query.error;
    if (error instanceof HttpError && error.status === 404) {
      return <NotInVersion {...props} suggestions={error.closeMatches} />;
    }
    return (
      <div role="alert" className="max-w-3xl">
        <h2 className="font-serif text-2xl font-semibold tracking-tight">
          Couldn't load this article
        </h2>
        <p className="mt-2 text-muted-foreground">
          {error instanceof HttpError && error.code
            ? error.message
            : "ExactDocs didn't answer. Check that it is running, then try again."}
        </p>
        <button
          type="button"
          onClick={() => query.refetch()}
          className={`${action} mt-4 cursor-pointer bg-primary text-primary-foreground hover:bg-primary/90`}
        >
          Try again
        </button>
      </div>
    );
  }
  return (
    <Body
      article={query.data}
      owner={owner}
      repo={repo}
      library={library}
      version={version}
      tags={props.tags}
    />
  );
}
