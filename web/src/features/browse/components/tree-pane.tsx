import { useCallback } from "react";
import type { VersionArgs } from "../api/browse-queries";
import { useTree } from "../hooks/use-tree";
import { FileTree } from "./file-tree";

interface TreePaneProps {
  target: VersionArgs;
  tagsParam: string | undefined;
  selected: string | undefined;
  onClearTags: () => void;
  onOpen: () => void;
}

const retry =
  "mt-1 inline-flex h-11 cursor-pointer items-center rounded-md bg-secondary px-3 text-sm font-medium outline-none transition-[background-color,transform] duration-150 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] lg:h-9";

const bars = [
  ["a", "w-28"],
  ["b", "w-40"],
  ["c", "w-32"],
  ["d", "w-36"],
  ["e", "w-24"],
  ["f", "w-44"],
  ["g", "w-32"],
] as const;

function Skeleton() {
  return (
    <div role="status" aria-busy="true" className="py-2">
      <span className="sr-only">Loading files</span>
      <ul aria-hidden="true" className="space-y-1 motion-safe:animate-pulse">
        {bars.map(([id, w], i) => (
          <li
            key={id}
            className="flex h-8 items-center gap-2"
            style={{ paddingLeft: `${(i % 3) * 12 + 8}px` }}
          >
            <span className="size-4 shrink-0 rounded bg-muted-foreground/[0.14]" />
            <span className={`h-3.5 rounded bg-muted-foreground/[0.14] ${w}`} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The files of one version and tag filter. Mount it with a `key`, so changing either starts afresh. */
export function TreePane({ target, tagsParam, selected, onClearTags, onOpen }: TreePaneProps) {
  const { owner, repo, ref, sha } = target;
  const tree = useTree({ owner, repo, ref, sha, tags: tagsParam, selected });
  const { scopes, loadMore } = tree;
  const scopeState = useCallback(
    (scope: string) => {
      const status = scopes[scope]?.status;
      return status === "paging" ? "paging" : status === "error" ? "error" : "idle";
    },
    [scopes],
  );
  const tags = tagsParam?.split(",").filter(Boolean) ?? [];

  if (tree.status === "loading") return <Skeleton />;
  if (tree.status === "error") {
    return (
      <div role="alert" className="py-3 text-sm">
        <p className="text-muted-foreground">Couldn't load the files of {ref}.</p>
        <button type="button" onClick={() => loadMore("")} className={retry}>
          Try again
        </button>
      </div>
    );
  }
  if (tree.rows.length === 0) {
    return (
      <div className="py-3 text-sm">
        <p className="font-medium">
          {tags.length > 0 ? `No articles tagged ${tags.join(" or ")}` : "Nothing imported here"}
        </p>
        <p className="mt-1 text-muted-foreground">
          {tags.length > 0
            ? `${ref} has no article with ${tags.length > 1 ? "any of these tags" : "this tag"}.`
            : `${ref} has no articles. Its import may have skipped every file.`}
        </p>
        {tags.length > 0 && (
          <button type="button" onClick={onClearTags} className={retry}>
            Show all articles
          </button>
        )}
      </div>
    );
  }
  return (
    <FileTree
      owner={owner}
      repo={repo}
      version={ref}
      tags={tagsParam}
      selected={selected}
      rows={tree.rows}
      scopeState={scopeState}
      label={`Files of ${ref}`}
      onToggle={tree.toggle}
      onMore={loadMore}
      onOpen={onOpen}
    />
  );
}
