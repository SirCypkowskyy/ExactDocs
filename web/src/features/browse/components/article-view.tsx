import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, FileQuestion } from "lucide-react";
import { Fragment } from "react";
import { HttpError } from "@/shared/lib/http";
import { articleQueryOptions } from "../api/browse-queries";
import {
  type Article,
  closeMatches,
  commitUrl,
  HOST_NAMES,
  type LibraryDetail,
  safeHref,
  shortSha,
  type Version,
} from "../model/browse";

interface ArticleViewProps {
  owner: string;
  repo: string;
  library: LibraryDetail;
  version: Version;
  path: string;
  tags: string | undefined;
}

const external =
  "inline-flex min-h-11 items-center gap-1 rounded-md px-1 text-sm font-medium underline decoration-mark/40 underline-offset-4 outline-none hover:decoration-mark focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8";

/** A repository path, allowed to break after each slash instead of in the middle of a word. */
export function PathText({ path }: { path: string }) {
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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-0">
      {file && (
        <a href={file} target="_blank" rel="noopener noreferrer" className={external}>
          View file on {host ?? "the host"}
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
          <span className="sr-only">
            at commit {shortSha(version.commit_sha)} (opens a new tab)
          </span>
        </a>
      )}
      {commit ? (
        <a href={commit} target="_blank" rel="noopener noreferrer" className={external}>
          Commit <code className="font-mono">{shortSha(version.commit_sha)}</code>
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
          <span className="sr-only">(opens a new tab)</span>
        </a>
      ) : (
        <p className="text-sm text-muted-foreground" title={version.commit_sha}>
          Commit <code className="font-mono">{shortSha(version.commit_sha)}</code>
          {" · no link, this host is not recognised"}
        </p>
      )}
    </div>
  );
}

function ArticleSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-4 motion-safe:animate-pulse">
      <span className="block h-4 w-2/3 max-w-sm rounded bg-muted-foreground/10" />
      <span className="block h-8 w-1/2 rounded bg-muted-foreground/10" />
      <span className="block h-5 w-40 rounded bg-muted-foreground/10" />
      <span className="mt-8 block h-64 rounded bg-muted-foreground/10" />
    </div>
  );
}

function NotInVersion({
  owner,
  repo,
  version,
  path,
  tags,
  suggestions,
}: Omit<ArticleViewProps, "library"> & { suggestions: string[] }) {
  return (
    <div className="fade-in max-w-2xl">
      <FileQuestion aria-hidden="true" className="mb-4 size-8 text-muted-foreground" />
      <h2 className="font-serif text-2xl font-semibold tracking-tight">
        Not in <span className="font-mono text-[0.9em]">{version.ref}</span>
      </h2>
      <p className="mt-2 text-muted-foreground">
        This version has no{" "}
        <code className="font-mono text-sm text-foreground [overflow-wrap:anywhere]">
          <PathText path={path} />
        </code>
        . It may have been added later, moved or removed. The tree shows what this version does
        contain.
      </p>
      {suggestions.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-medium">Close matches in this version</h3>
          <ul className="mt-1 -mx-2">
            {suggestions.map((s) => (
              <li key={s}>
                <Link
                  to="/libraries/$owner/$repo"
                  params={{ owner, repo }}
                  search={{ version: version.ref, path: s, tags }}
                  className="flex min-h-11 items-center rounded-md px-2 font-mono text-sm underline decoration-mark/40 underline-offset-4 outline-none hover:decoration-mark focus-visible:ring-2 focus-visible:ring-ring [overflow-wrap:anywhere]"
                >
                  <PathText path={s} />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Link
        to="/libraries/$owner/$repo"
        params={{ owner, repo }}
        search={{ version: version.ref, tags }}
        className="mt-6 inline-flex h-11 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground outline-none transition-[background-color,transform] duration-150 hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.97]"
      >
        Show the root of {version.ref}
      </Link>
    </div>
  );
}

function Body({
  article,
  library,
  version,
}: {
  article: Article;
  library: LibraryDetail;
  version: Version;
}) {
  return (
    <article className="fade-in min-w-0">
      <p className="font-mono text-[13px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
        <PathText path={article.path} />
      </p>
      <h2 className="mt-1 font-serif text-2xl font-semibold tracking-tight text-balance [overflow-wrap:anywhere] sm:text-3xl">
        {article.title}
      </h2>
      {article.tags.length > 0 && (
        <ul aria-label="Tags" className="mt-3 flex flex-wrap gap-1.5">
          {article.tags.map((t) => (
            <li
              key={t}
              className="rounded-md bg-secondary px-2 py-0.5 text-[13px] text-secondary-foreground"
            >
              {t}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2">
        <CommitLinks library={library} version={version} fileUrl={article.source_url} />
      </div>
      <h3 className="sr-only">Source text</h3>
      {/* Verbatim text, set as text: nothing from the repository is ever parsed as HTML (#51 renders it). */}
      <pre className="mt-5 max-w-[84ch] overflow-x-auto rounded-lg bg-secondary/60 p-4 font-mono text-[13.5px] leading-6 break-words whitespace-pre-wrap sm:p-5">
        {article.content}
      </pre>
    </article>
  );
}

/** The article pane: loading, the text, "not in this version" with suggestions, or an error. */
export function ArticleView(props: ArticleViewProps) {
  const { owner, repo, library, version, path } = props;
  const query = useQuery(articleQueryOptions(owner, repo, version.ref, path));
  if (query.isPending) {
    return (
      <div role="status" aria-busy="true">
        <span className="sr-only">Loading {path}</span>
        <ArticleSkeleton />
      </div>
    );
  }
  if (query.isError) {
    const gone = query.error instanceof HttpError && query.error.status === 404;
    if (gone) {
      return <NotInVersion {...props} suggestions={closeMatches(query.error.message)} />;
    }
    return (
      <div role="alert" className="max-w-xl">
        <h2 className="font-serif text-2xl font-semibold tracking-tight">
          Couldn't load this article
        </h2>
        <p className="mt-2 text-muted-foreground">
          {query.error instanceof HttpError && query.error.code
            ? query.error.message
            : "ExactDocs didn't answer. Check that it is running, then try again."}
        </p>
        <button
          type="button"
          onClick={() => query.refetch()}
          className="mt-4 inline-flex h-11 cursor-pointer items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground outline-none transition-[background-color,transform] duration-150 hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.97]"
        >
          Try again
        </button>
      </div>
    );
  }
  return <Body article={query.data} library={library} version={version} />;
}
